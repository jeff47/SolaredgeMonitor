# solaredge_monitor/tests/test_integration_harness.py

import pytest

from solaredge_monitor.tests.integration_harness import (
    IntegrationScenario,
    IntegrationTestHarness,
)


@pytest.fixture()
def harness() -> IntegrationTestHarness:
    return IntegrationTestHarness()


def test_midday_production_is_healthy(harness: IntegrationTestHarness):
    scenario = IntegrationScenario(
        name="midday-healthy",
        phase="mid_day",
        values={
            "INV-A": {"status": 4, "pac_w": 1500, "vdc_v": 410},
            "INV-B": {"status": 4, "pac_w": 1475, "vdc_v": 405},
        },
    )

    result = harness.run(scenario)

    assert result.health.system_ok
    assert result.alerts == []


def test_faulty_inverter_triggers_alert(harness: IntegrationTestHarness):
    scenario = IntegrationScenario(
        name="midday-fault",
        phase="mid_day",
        values={
            "INV-A": {"status": 4, "pac_w": 1200, "vdc_v": 390},
            "INV-B": {"status": 7, "pac_w": 0, "vdc_v": 0},
        },
    )

    result = harness.run(scenario)

    assert not result.health.system_ok
    assert len(result.alerts) == 1
    assert result.alerts[0].inverter_name == "INV-B"


def test_pre_dawn_zero_pac_suppresses_daytime_alerts(harness: IntegrationTestHarness):
    scenario = IntegrationScenario(
        name="pre-dawn-zero-pac",
        phase="pre_dawn",
        values={
            "INV-A": {"status": 4, "pac_w": 0, "vdc_v": 360},
            "INV-B": {"status": 4, "pac_w": 0, "vdc_v": 355},
        },
    )

    result = harness.run(scenario)

    assert result.now.hour == 5  # sanity check for phase mapping
    assert result.health.system_ok  # low-light override should treat this as OK
    assert result.alerts == []  # Alert logic should suppress during darkness
