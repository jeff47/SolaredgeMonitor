from __future__ import annotations

from types import SimpleNamespace

from solaredge_monitor.services import modbus_reader


class DummyLog:
    def __init__(self):
        self.debug_messages = []
        self.warning_messages = []

    def debug(self, msg, *args):
        self.debug_messages.append((msg, args))

    def warning(self, msg, *args):
        self.warning_messages.append((msg, args))


def test_apply_scale_handles_valid_and_invalid_values():
    assert modbus_reader.apply_scale(25, -1) == 2.5
    assert modbus_reader.apply_scale(None, -1) is None
    assert modbus_reader.apply_scale(25, None) is None
    assert modbus_reader.apply_scale("bad", "scale") is None


def test_read_inverter_returns_none_when_connect_fails(monkeypatch):
    instances = []

    class FakeClient:
        def __init__(self, **kwargs):
            self.disconnected = False
            instances.append(self)

        def connect(self):
            return False

        def disconnect(self):
            self.disconnected = True

    monkeypatch.setattr(modbus_reader, "ModbusInverter", FakeClient)
    log = DummyLog()
    reader = modbus_reader.ModbusReader(
        SimpleNamespace(inverters=[], retries=2, timeout=1.5),
        log,
    )

    result = reader.read_inverter(SimpleNamespace(name="INV-A", host="h", port=1502, unit=1))

    assert result is None
    assert instances[0].disconnected is True
    assert any("INV-A" in msg for msg, _ in log.warning_messages)


def test_read_inverter_scales_values_and_defaults_identity(monkeypatch):
    class FakeClient:
        def __init__(self, **kwargs):
            self.values = {
                "c_serialnumber": {},
                "c_model": {},
                "status": {"status": 4},
                "power_ac": {"power_ac": 25},
                "power_ac_scale": {"power_ac_scale": 2},
                "voltage_dc": {"voltage_dc": 4000},
                "voltage_dc_scale": {"voltage_dc_scale": -1},
                "current_dc": {"current_dc": 123},
                "current_dc_scale": {"current_dc_scale": -2},
                "energy_total": {"energy_total": 456},
                "energy_total_scale": {"energy_total_scale": 1},
            }

        def connect(self):
            return True

        def read(self, key):
            return self.values[key]

        def disconnect(self):
            pass

    monkeypatch.setattr(modbus_reader, "ModbusInverter", FakeClient)
    reader = modbus_reader.ModbusReader(
        SimpleNamespace(inverters=[], retries=2, timeout=1.5),
        DummyLog(),
    )

    result = reader.read_inverter(SimpleNamespace(name="INV-A", host="h", port=1502, unit=1))

    assert result.serial == "unknown"
    assert result.model == "unknown"
    assert result.status == 4
    assert result.pac_w == 2500.0
    assert result.vdc_v == 400.0
    assert result.idc_a == 1.23
    assert result.total_wh == 4560.0


def test_read_all_marks_offline_inverters(monkeypatch):
    reader = modbus_reader.ModbusReader(
        SimpleNamespace(
            inverters=[
                SimpleNamespace(name="INV-A"),
                SimpleNamespace(name="INV-B"),
            ],
            retries=2,
            timeout=1.5,
        ),
        DummyLog(),
    )

    monkeypatch.setattr(
        reader,
        "read_inverter",
        lambda inv_cfg: None if inv_cfg.name == "INV-B" else SimpleNamespace(name=inv_cfg.name),
    )

    result = reader.read_all()

    assert set(result.keys()) == {"INV-A", "INV-B"}
    assert result["INV-A"].name == "INV-A"
    assert result["INV-B"] is None
