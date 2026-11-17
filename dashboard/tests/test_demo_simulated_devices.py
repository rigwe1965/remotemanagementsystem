"""Pages must not hand work to an agent that does not exist (the hosted demo's devices are simulated), and must leave real
devices exactly as they were. One simulated-device test and one real-device test per page, plus the helper."""
import uuid
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

from utils.demo import SIMULATED_AGENT, demo_note, is_simulated

C = "utils.api_client.RMMClient."


def _app(path: str) -> AppTest:
    at = AppTest.from_file(path)
    at.session_state["access_token"] = f"fake-token-{uuid.uuid4().hex[:8]}"
    at.session_state["refresh_token"] = "fake-refresh-token"
    at.session_state["user"] = {"id": "u1", "email": "admin@test.local", "role": "admin", "full_name": "Test Admin"}
    at.session_state["_org_settings"] = {"currency": "USD", "timezone": "UTC"}
    return at


def _device(simulated: bool, **extra):
    d = {"id": "sim1" if simulated else "real1", "hostname": "DEMO-PC" if simulated else "REAL-PC", "platform": "windows",
         "is_online": True, "is_agentless": False, "status": "healthy", "ip_address": "10.0.0.5", "os_name": "Windows 11",
         "agent_version": SIMULATED_AGENT if simulated else "1.4.2"}
    d.update(extra)
    return d


def _button(at, label):
    return next(b for b in at.button if b.label == label)


def _infos(at):
    return " ".join(i.value for i in at.info)


class TestHelper:
    def test_only_the_demo_marker_counts(self):
        assert is_simulated({"agent_version": SIMULATED_AGENT})
        assert not is_simulated({"agent_version": "1.4.2"})
        assert not is_simulated({})
        assert not is_simulated(None)

    def test_note_names_the_action(self):
        note = demo_note("reboot")
        assert "demo device" in note and "simulated" in note and "reboot" in note


class TestDiskManagement:
    DISKS = {"latest_metrics": {"disks": [{"drive": "C:", "used_pct": 45.0, "total_gb": 500, "used_gb": 225}]}}

    def _click(self, simulated):
        at = _app("../pages/14_Disk_Management.py")
        with patch(C + "list_devices", return_value=({"items": [_device(simulated, **self.DISKS)]}, None)), \
             patch(C + "queue_device_task", return_value=({}, None)) as queue, patch("streamlit.page_link"):
            at.run()
            _button(at, "Defragment").click().run()
        return at, queue

    def test_simulated_device_explains_and_queues_nothing(self):
        at, queue = self._click(True)
        assert not at.exception
        assert "demo device" in _infos(at) and "defragment" in _infos(at)
        assert not any("queued" in s.value for s in at.success)
        queue.assert_not_called()

    def test_real_device_still_queues(self):
        at, queue = self._click(False)
        assert not at.exception
        queue.assert_called_once_with("real1", "defrag", timeout=1800)
        assert any("Defragment queued" in s.value for s in at.success)


class TestMaintenance:
    def _run(self, simulated, button, tick=True):
        at = _app("../pages/15_Maintenance.py")
        dev = _device(simulated, os_version="11", last_seen="2026-01-01T00:00:00Z")
        with patch(C + "list_devices", return_value=({"items": [dev]}, None)), patch(C + "_get", return_value=(None, "no history")), \
             patch(C + "reboot_device", return_value=({}, None)) as reboot, \
             patch(C + "queue_device_task", return_value=({}, None)) as queue, patch("streamlit.page_link"):
            at.run()
            if tick:
                at.checkbox[0].check().run()
            _button(at, button).click().run()
        return at, reboot, queue

    def test_simulated_reboot_is_not_sent(self):
        at, reboot, _ = self._run(True, "Reboot")
        assert not at.exception
        assert "demo device" in _infos(at) and "reboot" in _infos(at)
        assert not any("command sent" in s.value for s in at.success)
        reboot.assert_not_called()

    def test_simulated_queued_task_is_not_queued(self):
        at, _, queue = self._run(True, "Delete Temp Files")
        assert not at.exception
        assert "demo device" in _infos(at)
        queue.assert_not_called()

    def test_real_device_reboot_and_task_unchanged(self):
        at, reboot, _ = self._run(False, "Reboot")
        reboot.assert_called_once_with("real1")
        assert any("Reboot command sent" in s.value for s in at.success)
        at, _, queue = self._run(False, "Delete Temp Files")
        queue.assert_called_once_with("real1", "clean_temp")


class TestScripts:
    SCRIPT = {"id": "s1", "name": "Clean Temp Files", "file_type": "ps1", "is_builtin": True, "os_target": "windows",
              "created_at": "2026-01-01T00:00:00Z", "description": "Cleans temp dirs", "content": "Remove-Item ..."}

    def _run(self, simulated):
        at = _app("../pages/16_Scripts.py")
        dev = _device(simulated)
        with patch(C + "list_scripts", return_value=([self.SCRIPT], None)), patch(C + "list_devices", return_value=({"items": [dev]}, None)), \
             patch(C + "list_script_runs", return_value=({"items": []}, None)), \
             patch(C + "run_script", return_value=({"queued": 1}, None)) as run, patch("streamlit.page_link"):
            at.run()
            at.multiselect[0].select(dev["hostname"]).run()
            _button(at, "Run").click().run()
        return at, run

    def test_simulated_device_is_not_sent_a_script(self):
        at, run = self._run(True)
        assert not at.exception
        assert "demo device" in _infos(at) and "run a script" in _infos(at)
        run.assert_not_called()

    def test_real_device_still_runs(self):
        at, run = self._run(False)
        assert not at.exception
        run.assert_called_once()
        assert run.call_args.args[1] == ["real1"]


class TestTerminal:
    def _connect(self, simulated, command=None):
        at = _app("../pages/14_Terminal.py")
        with patch(C + "list_devices", return_value=({"items": [_device(simulated)]}, None)), \
             patch(C + "create_terminal_session", return_value=({"id": "sess-1"}, None)) as create, \
             patch(C + "send_terminal_command", return_value=({}, None)) as send, \
             patch(C + "get_terminal_output", return_value=({"session": {}, "output": [], "pending_commands": 0}, None)), \
             patch(C + "close_terminal_session", return_value=({}, None)) as close, patch("streamlit.page_link"):
            at.run()
            _button(at, "Connect").click().run()
            if command:
                at.text_input(key="_term_cmd_input").set_value(command).run()
                _button(at, "Send ▶").click().run()
        return at, create, send, close

    def test_simulated_device_gets_a_local_session_and_no_api_calls(self):
        at, create, send, _ = self._connect(True, command="ipconfig")
        assert not at.exception
        create.assert_not_called()
        send.assert_not_called()
        text = " ".join(c["content"] for c in at.session_state["_term_output_buf"])
        assert "$ ipconfig" in text and "Not run" in text and "simulated" in text

    def test_simulated_session_disconnects_without_calling_the_server(self):
        at = _app("../pages/14_Terminal.py")
        with patch(C + "list_devices", return_value=({"items": [_device(True)]}, None)), \
             patch(C + "close_terminal_session", return_value=({}, None)) as close, patch("streamlit.page_link"):
            at.run()
            _button(at, "Connect").click().run()
            _button(at, "Disconnect").click().run()
        assert not at.exception
        close.assert_not_called()
        assert at.session_state["_term_session_id"] is None

    def test_real_device_still_opens_a_real_session_and_sends(self):
        at, create, send, _ = self._connect(False, command="whoami")
        assert not at.exception
        create.assert_called_once_with("real1")
        send.assert_called_once_with("sess-1", "whoami")


class TestDevicesPage:
    def _click(self, simulated, label):
        at = _app("../pages/04_Devices.py")
        dev = _device(simulated, customer_name="Acme Corp")
        with patch(C + "list_devices", return_value=({"items": [dev]}, None)),              patch(C + "get_platform_counts", return_value=({"by_platform": {"windows": 1}, "agentless": 0}, None)),              patch(C + "get_agent_update_info", return_value=({}, None)),              patch(C + "list_customers", return_value=({"items": [{"id": "c1", "name": "Acme Corp"}]}, None)),              patch(C + "get_device_metrics", return_value=({}, None)),              patch(C + "assistant_get_conversation", return_value=(None, "skip")),              patch(C + "reboot_device", return_value=({}, None)) as reboot,              patch(C + "shutdown_device", return_value=({}, None)) as shutdown, patch("streamlit.page_link"):
            at.run(timeout=30)
            next(b for b in at.button if b.label == label).click().run(timeout=30)
        return at, reboot, shutdown

    def test_simulated_reboot_and_shutdown_are_not_sent(self):
        at, reboot, shutdown = self._click(True, "Reboot")
        assert not at.exception
        assert "demo device" in _infos(at) and "reboot" in _infos(at)
        assert not any("queued" in s.value for s in at.success)
        reboot.assert_not_called()
        at, reboot, shutdown = self._click(True, "Shutdown")
        assert "demo device" in _infos(at) and "shut down" in _infos(at)
        shutdown.assert_not_called()

    def test_real_device_reboot_and_shutdown_still_sent(self):
        at, reboot, _ = self._click(False, "Reboot")
        reboot.assert_called_once_with("real1")
        assert any("Reboot queued" in s.value for s in at.success)
        at, _, shutdown = self._click(False, "Shutdown")
        shutdown.assert_called_once_with("real1")

