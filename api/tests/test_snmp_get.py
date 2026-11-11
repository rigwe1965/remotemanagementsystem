"""
_snmp_get against a fake SNMP v1 device on the loopback address (127.0.0.1, a random UDP port).

tests/test_snmp_tasks.py replaces _snmp_get with a mock, so none of those tests runs the real pysnmp
call. These do: they send a real SNMP GET over UDP to a tiny fake agent started inside the test and
nothing leaves this machine. They cover a good read, a missing OID, a wrong community string, a
device that does not answer, big counter values and a missing pysnmp install.
"""
import socket
import sys
import threading

import pytest

from pyasn1.codec.ber import decoder, encoder
from pysnmp.proto import api

import tasks.snmp_tasks as snmp_tasks

OID_BATTERY = "1.3.6.1.2.1.33.1.2.4.0"
OID_IN_OCTETS = "1.3.6.1.2.1.2.2.1.10.1"


class FakeSnmpDevice(threading.Thread):
    """One SNMP v1 device. `values` maps an OID string to an int (INTEGER) or ("counter", int) (Counter32).
    A wrong community string gets no answer at all, like a real agent. An unknown OID gets noSuchName."""

    def __init__(self, community, values):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.1)
        self.port = self.sock.getsockname()[1]
        self.community = community
        self.values = values
        self._stop_flag = False

    def run(self):
        while not self._stop_flag:
            try:
                data, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                return
            p_mod = api.PROTOCOL_MODULES[int(api.decodeMessageVersion(data))]
            request, _ = decoder.decode(data, asn1Spec=p_mod.Message())
            if str(p_mod.apiMessage.get_community(request)) != self.community:
                continue
            response = p_mod.apiMessage.get_response(request)
            response_pdu = p_mod.apiMessage.get_pdu(response)
            var_binds = []
            for oid, value in p_mod.apiPDU.get_varbinds(p_mod.apiMessage.get_pdu(request)):
                stored = self.values.get(str(oid))
                if stored is None:
                    p_mod.apiPDU.set_error_status(response_pdu, 2)  # noSuchName
                    var_binds.append((oid, value))
                elif isinstance(stored, tuple):
                    var_binds.append((oid, p_mod.Counter(stored[1])))
                else:
                    var_binds.append((oid, p_mod.Integer(stored)))
            p_mod.apiPDU.set_varbinds(response_pdu, var_binds)
            self.sock.sendto(encoder.encode(response), addr)

    def close(self):
        self._stop_flag = True
        self.join(timeout=2)
        self.sock.close()


@pytest.fixture
def device():
    d = FakeSnmpDevice("public", {OID_BATTERY: 87, OID_IN_OCTETS: ("counter", 3_000_000_000)})
    d.start()
    yield d
    d.close()


@pytest.fixture(autouse=True)
def fast_timeouts(monkeypatch):
    # A device that does not answer must not stall the suite for seconds.
    monkeypatch.setattr(snmp_tasks, "_SNMP_TIMEOUT", 1)
    monkeypatch.setattr(snmp_tasks, "_SNMP_RETRIES", 0)


class TestSnmpGet:
    def test_reads_an_integer_value(self, device):
        assert snmp_tasks._snmp_get("127.0.0.1", "public", OID_BATTERY, port=device.port) == (87, None)

    def test_reads_a_counter_larger_than_a_signed_32_bit_int(self, device):
        # Interface octet counters are Counter32 and routinely exceed 2**31.
        assert snmp_tasks._snmp_get("127.0.0.1", "public", OID_IN_OCTETS, port=device.port) == (3_000_000_000, None)

    def test_missing_oid_returns_an_error_string_not_a_value(self, device):
        value, err = snmp_tasks._snmp_get("127.0.0.1", "public", "1.3.6.1.2.1.99.9.9.0", port=device.port)
        assert value is None
        assert "noSuchName" in err

    def test_wrong_community_string_gets_no_value(self, device):
        value, err = snmp_tasks._snmp_get("127.0.0.1", "wrong", OID_BATTERY, port=device.port)
        assert value is None
        assert err and "No SNMP response" in err

    def test_device_that_does_not_answer_returns_an_error_and_does_not_raise(self):
        # Nothing is listening on this port.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        value, err = snmp_tasks._snmp_get("127.0.0.1", "public", OID_BATTERY, port=port)
        assert value is None
        assert isinstance(err, str) and err

    def test_back_to_back_calls_each_get_a_clean_event_loop(self, device):
        # The task polls many OIDs in a row, each call running its own asyncio loop.
        results = [snmp_tasks._snmp_get("127.0.0.1", "public", OID_BATTERY, port=device.port) for _ in range(5)]
        assert results == [(87, None)] * 5

    def test_missing_pysnmp_install_is_reported_as_such(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "pysnmp.hlapi.v1arch.asyncio", None)  # makes the import raise ImportError
        assert snmp_tasks._snmp_get("127.0.0.1", "public", OID_BATTERY) == (None, "pysnmp_not_installed")
