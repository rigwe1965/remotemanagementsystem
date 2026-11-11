"""
Shared test setup for the dashboard.

Every page test builds an `AppTest.from_file(...)` and calls `.run()`. Streamlit's default allowance for
one script run is 3 seconds, which a CI runner meets but a slower machine (a laptop with antivirus or
application-control scanning every import, a cold start, a busy disk) does not: 27 of these tests failed
with "AppTest script run timed out after 3(s)" on such a machine while passing in CI. Nothing in them was
wrong, only the allowance.

This raises the default to 30 seconds for every AppTest built from a file. Set APPTEST_TIMEOUT (seconds)
to change it. A test that passes its own `default_timeout=` or `run(timeout=...)` keeps that value, and a
page that really hangs still fails, just after 30 seconds instead of 3.
"""
import os

import pytest
from streamlit.testing.v1 import AppTest

_DEFAULT_TIMEOUT = float(os.getenv("APPTEST_TIMEOUT", "30"))


@pytest.fixture(autouse=True)
def _generous_apptest_timeout(monkeypatch):
    original = AppTest.from_file

    def from_file(script_path, *, default_timeout=_DEFAULT_TIMEOUT, **kwargs):
        return original(script_path, default_timeout=default_timeout, **kwargs)

    monkeypatch.setattr(AppTest, "from_file", staticmethod(from_file))
