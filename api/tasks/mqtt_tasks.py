"""
MQTT subscriber Celery task.
Connects to external MQTT broker, subscribes to sensor topics, writes DeviceSensorReading rows.

Topic convention: {MQTT_TOPIC_PREFIX}/{device_id}/sensors/{sensor_type}
Payload: JSON  {"value": <float>, "unit": "<str>", "channel": "<str|null>"}

Set MQTT_HOST to enable. No-op (logs warning) if unset.
"""
import json
import logging
import os
from datetime import datetime, timezone

from tasks.celery_app import celery

logger = logging.getLogger(__name__)

_MQTT_HOST = None
_MQTT_PORT = 1883
_MQTT_PREFIX = "rmm"
_MQTT_USER = None
_MQTT_PASS = None

_app = None


def _get_app():
    global _app
    if _app is None:
        from app import create_app
        _app = create_app()
    return _app


def _load_config():
    global _MQTT_HOST, _MQTT_PORT, _MQTT_PREFIX, _MQTT_USER, _MQTT_PASS
    _MQTT_HOST = os.getenv("MQTT_HOST", "").strip() or None
    _MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
    _MQTT_PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "rmm").strip()
    _MQTT_USER = os.getenv("MQTT_USERNAME", "").strip() or None
    _MQTT_PASS = os.getenv("MQTT_PASSWORD", "").strip() or None


@celery.task(name="tasks.mqtt_tasks.subscribe_mqtt_sensors", bind=True, max_retries=3)
def subscribe_mqtt_sensors(self):
    _load_config()

    if not _MQTT_HOST:
        logger.debug("MQTT_HOST not set — skipping MQTT sensor poll")
        return

    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        logger.warning("paho-mqtt not installed — MQTT sensor polling disabled. pip install paho-mqtt")
        return

    app = _get_app()

    received = []

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            topic = f"{_MQTT_PREFIX}/+/sensors/+"
            client.subscribe(topic)
            logger.info("MQTT subscribed to %s", topic)
        else:
            logger.warning("MQTT connection failed, rc=%d", rc)

    def on_message(client, userdata, msg):
        try:
            parts = msg.topic.split("/")
            # Expected: prefix / device_id / sensors / sensor_type
            if len(parts) < 4:
                return
            device_id = parts[-3]
            sensor_type = parts[-1]
            payload = json.loads(msg.payload.decode("utf-8"))
            value = float(payload["value"])
            received.append({
                "device_id": device_id,
                "sensor_type": sensor_type,
                "value": value,
                "unit": payload.get("unit"),
                "channel": payload.get("channel"),
            })
        except Exception as exc:
            logger.warning("MQTT message parse error on topic %s: %s", msg.topic, exc)

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    if _MQTT_USER:
        client.username_pw_set(_MQTT_USER, _MQTT_PASS)

    try:
        client.connect(_MQTT_HOST, _MQTT_PORT, keepalive=10)
        client.loop_start()
        import time
        time.sleep(5)  # collect messages for 5 seconds
        client.loop_stop()
        client.disconnect()
    except Exception as exc:
        logger.warning("MQTT connection error (%s:%d): %s", _MQTT_HOST, _MQTT_PORT, exc)
        return

    if not received:
        return

    from models.device import Device, DeviceSensorReading, SENSOR_TYPES

    with app.app_context():
        from extensions import db
        now = datetime.now(timezone.utc)
        inserted = 0

        for item in received:
            if item["sensor_type"] not in SENSOR_TYPES:
                logger.debug("MQTT: unknown sensor_type '%s' — skipped", item["sensor_type"])
                continue
            device = db.session.get(Device, item["device_id"])
            if not device:
                logger.debug("MQTT: device_id '%s' not found — skipped", item["device_id"])
                continue

            db.session.add(DeviceSensorReading(
                device_id=item["device_id"],
                customer_id=device.customer_id,
                collected_at=now,
                sensor_type=item["sensor_type"],
                value=item["value"],
                unit=item["unit"],
                channel=item["channel"],
                source="mqtt",
            ))
            inserted += 1

        if inserted:
            db.session.commit()
            logger.info("MQTT: inserted %d sensor readings", inserted)
            try:
                from utils.events import publish_event
                publish_event("sensor_reading", {"source": "mqtt", "count": inserted})
            except Exception:
                pass
