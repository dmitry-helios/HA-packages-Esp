"""Home Assistant test setup; all email fixtures are synthetic."""

import pytest


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    yield
