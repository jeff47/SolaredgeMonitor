from solaredge_monitor.config import Config

CONF = """
[modbus]
inverters = INV-A

[inverter:INV-A]
host = 1.1.1.1

[retention]
snapshot_days = 15
summary_days = 45
vacuum_after_prune = false
"""


def test_retention_config(tmp_path):
    conf_path = tmp_path / "solar.conf"
    conf_path.write_text(CONF)
    cfg = Config.load(str(conf_path))
    assert cfg.retention.snapshot_days == 15
    assert cfg.retention.summary_days == 45
    assert cfg.retention.vacuum_after_prune is False
