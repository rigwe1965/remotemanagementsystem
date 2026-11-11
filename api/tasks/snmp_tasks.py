"""
SNMP polling Celery task.
Polls devices with device_type in (switch, ap, ups, router) that have
metadata_.snmp_community set. Writes DeviceSensorReading rows for UPS
battery/load and interface traffic.

Requires: pip install pysnmp
Gracefully skips if pysnmp not installed or device unreachable.
"""
import logging
import os
from datetime import datetime, timezone

from tasks.celery_app import celery

logger = logging.getLogger(__name__)

_SNMP_TIMEOUT = int(os.getenv("SNMP_TIMEOUT", "3"))
_SNMP_RETRIES = 1

# OIDs
_OID_UPS_BATTERY_PCT   = "1.3.6.1.2.1.33.1.2.4.0"   # upsEstimatedChargeRemaining
_OID_UPS_LOAD_PCT      = "1.3.6.1.2.1.33.1.4.4.1.5.1"  # upsOutputPercentLoad (index 1)
_OID_IF_IN_OCTETS      = "1.3.6.1.2.1.2.2.1.10"     # ifInOctets (table — append .ifIndex)
_OID_IF_OUT_OCTETS     = "1.3.6.1.2.1.2.2.1.16"     # ifOutOctets (table — append .ifIndex)

_SNMP_DEVICE_TYPES = {"switch", "ap", "ups", "router", "iot_gateway"}

from tasks._app_singleton import get_app as _get_app


def _snmp_get(ip: str, community: str, oid: str, port: int = 161):
    """Single SNMP GET (v1, community string). Returns (value, None) or (None, error_string).

    pysnmp 7.x is asyncio-first, so the one request runs to completion on its own event
    loop here and the caller (a synchronous Celery task) sees the same blocking call as
    before. `port` exists so tests can point at a local fake device.
    """
    try:
        import asyncio
        from pysnmp.hlapi.v1arch.asyncio import (
            SnmpDispatcher, CommunityData, UdpTransportTarget,
            ObjectType, ObjectIdentity, get_cmd,
        )
    except ImportError:
        return None, "pysnmp_not_installed"

    async def _get():
        dispatcher = SnmpDispatcher()
        try:
            target = await UdpTransportTarget.create(
                (ip, port), timeout=_SNMP_TIMEOUT, retries=_SNMP_RETRIES,
            )
            return await get_cmd(
                dispatcher,
                CommunityData(community, mpModel=0),
                target,
                ObjectType(ObjectIdentity(oid)),
            )
        finally:
            dispatcher.close()

    try:
        error_indication, error_status, _error_index, var_binds = asyncio.run(_get())
        if error_indication or error_status:
            return None, str(error_indication or error_status)
        _, val = var_binds[0]
        return int(val), None
    except Exception as exc:
        return None, str(exc)


@celery.task(name="tasks.snmp_tasks.poll_snmp_devices", bind=True, max_retries=2)
def poll_snmp_devices(self):
    app = _get_app()
    with app.app_context():
        from extensions import db
        from models.device import Device, DeviceSensorReading

        # Find SNMP-capable devices
        candidates = Device.query.filter(
            Device.is_online == True,
            Device.device_type.in_(list(_SNMP_DEVICE_TYPES)),
        ).all()

        if not candidates:
            return 0

        snmp_devices = [
            d for d in candidates
            if d.metadata_ and d.metadata_.get("snmp_community")
        ]

        if not snmp_devices:
            logger.debug("poll_snmp_devices: no devices with snmp_community in metadata_")
            return 0

        now = datetime.now(timezone.utc)
        inserted = 0

        for device in snmp_devices:
            ip = device.ip_address
            community = device.metadata_["snmp_community"]
            dtype = device.device_type

            if not ip:
                continue

            readings = []

            if dtype == "ups":
                batt, err = _snmp_get(ip, community, _OID_UPS_BATTERY_PCT)
                if err == "pysnmp_not_installed":
                    logger.warning("pysnmp not installed — SNMP polling disabled. pip install pysnmp")
                    return 0
                if batt is not None:
                    readings.append(("ups_battery", float(batt), "%"))
                load, _ = _snmp_get(ip, community, _OID_UPS_LOAD_PCT)
                if load is not None:
                    readings.append(("ups_load", float(load), "%"))

            elif dtype in ("switch", "ap", "router"):
                # Poll interface index 1 by default (WAN/uplink)
                ifindex = device.metadata_.get("snmp_ifindex", 1)
                in_oct, _ = _snmp_get(ip, community, f"{_OID_IF_IN_OCTETS}.{ifindex}")
                out_oct, _ = _snmp_get(ip, community, f"{_OID_IF_OUT_OCTETS}.{ifindex}")
                # Convert raw octets to Mbps-equivalent float for trending (raw counter value)
                if in_oct is not None:
                    readings.append(("power_watts", float(in_oct), "octets_in"))
                if out_oct is not None:
                    readings.append(("power_watts", float(out_oct), "octets_out"))

            for sensor_type, value, unit in readings:
                db.session.add(DeviceSensorReading(
                    device_id=device.id,
                    customer_id=device.customer_id,
                    collected_at=now,
                    sensor_type=sensor_type,
                    value=value,
                    unit=unit,
                    channel=dtype,
                    source="snmp",
                ))
                inserted += 1

        if inserted:
            db.session.commit()
            logger.info("poll_snmp_devices: inserted %d readings from %d devices",
                        inserted, len(snmp_devices))
        return inserted
