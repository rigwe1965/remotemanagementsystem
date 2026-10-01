"""AppTest coverage for pages/18_IoT_Sensors.py (audits/testing_audit.md Finding C5)."""
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


def _authenticated_app_test(path: str, role: str = "admin", customer_id=None) -> AppTest:
    at = AppTest.from_file(path)
    at.session_state["access_token"] = "fake-token-for-apptest"
    at.session_state["refresh_token"] = "fake-refresh-token"
    at.session_state["user"] = {"id": "u1", "email": "admin@test.local", "role": role,
                                 "full_name": "Test Admin", "customer_id": customer_id}
    at.session_state["_org_settings"] = {"currency": "USD", "timezone": "UTC"}
    return at


_DEVICES = ({"items": [{"id": "d1", "hostname": "pi-01", "display_name": None, "customer_id": "c1"}]}, None)
_CUSTOMERS = ({"items": [{"id": "c1", "name": "Acme Corp"}]}, None)
_READINGS = ([
    {"sensor_type": "temperature", "value": 21.5, "collected_at": "2026-01-01T00:00:00Z", "channel": "sensor1", "source": "mqtt"},
    {"sensor_type": "temperature", "value": 22.0, "collected_at": "2026-01-01T01:00:00Z", "channel": "sensor1", "source": "mqtt"},
], None)


class TestIotSensorsPage:
    def test_renders_metric_for_readings(self):
        at = _authenticated_app_test("../pages/18_IoT_Sensors.py")
        with patch("utils.api_client.RMMClient.list_devices", return_value=_DEVICES), \
             patch("utils.api_client.RMMClient.list_customers", return_value=_CUSTOMERS), \
             patch("utils.api_client.RMMClient.get_sensor_data", return_value=_READINGS), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        metric_labels = " ".join(m.label for m in at.metric)
        assert "Temperature" in metric_labels

    def test_shows_info_when_no_devices(self):
        at = _authenticated_app_test("../pages/18_IoT_Sensors.py")
        with patch("utils.api_client.RMMClient.list_devices", return_value=({"items": []}, None)), \
             patch("utils.api_client.RMMClient.list_customers", return_value=_CUSTOMERS), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert any("No devices found" in i.value for i in at.info)

    def test_shows_info_when_no_readings_in_window(self):
        at = _authenticated_app_test("../pages/18_IoT_Sensors.py")
        with patch("utils.api_client.RMMClient.list_devices", return_value=_DEVICES), \
             patch("utils.api_client.RMMClient.list_customers", return_value=_CUSTOMERS), \
             patch("utils.api_client.RMMClient.get_sensor_data", return_value=([], None)), \
             patch("streamlit.page_link"):
            at.run()

        assert not at.exception
        assert any("No sensor readings" in i.value for i in at.info)
