"""Unit tests for configuration management."""

import tempfile
from pathlib import Path

import yaml

from quantflow.common.config import (
    AlertChannelConfig,
    AppConfig,
    DataConfig,
    MonitoringConfig,
    RiskConfig,
    _deep_merge,
    _load_env_overrides,
    _parse_env_value,
    _sanitize_config,
    _set_nested,
    load_config,
    resolve_config_path,
    save_config,
)


class TestAppConfig:
    def test_defaults(self):
        cfg = AppConfig()
        assert cfg.data.exchange == "okx"
        assert cfg.data.sandbox is False
        assert cfg.indicators.rsi_period == 14
        assert cfg.risk.position_limit_pct == 0.20
        assert cfg.risk.kill_switch_enabled is True
        assert cfg.execution.mode == "paper"

    def test_custom_values(self):
        cfg = AppConfig(data=DataConfig(sandbox=True), risk=RiskConfig(max_drawdown=-0.15))
        assert cfg.data.sandbox is True
        assert cfg.risk.max_drawdown == -0.15

    def test_risk_config_wires_kelly_and_var_confidence(self):
        """kelly_fraction and var_confidence are in default.yaml; they MUST be
        on RiskConfig or the YAML values are silently dropped (the bug that hid
        kelly_fraction for the entire v0.1.3 release)."""
        cfg = AppConfig()
        assert hasattr(cfg.risk, "kelly_fraction")
        assert hasattr(cfg.risk, "var_confidence")
        assert hasattr(cfg.risk, "cvar_limit")
        assert cfg.risk.kelly_fraction == 0.5
        assert cfg.risk.var_confidence == 0.95


class TestConfigSchemaDrift:
    """Guard against YAML<->pydantic schema drift.

    Every scalar key in default.yaml must resolve to a field on the matching
    AppConfig sub-model. A key present in YAML but absent from the model is
    silently dropped at load time — this is how kelly_fraction/var_confidence
    were ignored for a full release. This test fails the moment such drift is
    reintroduced.
    """

    def test_default_yaml_has_no_dropped_keys(self):
        from quantflow.common.config import _PACKAGE_DEFAULT_CONFIG

        with _PACKAGE_DEFAULT_CONFIG.open(encoding="utf-8") as handle:
            yml = yaml.safe_load(handle)

        cfg = AppConfig()
        drift: list[str] = []

        def walk(prefix: str, section, model) -> None:
            for key, value in (section or {}).items():
                if isinstance(value, dict):
                    sub = getattr(model, key, None)
                    if sub is None:
                        drift.append(f"{prefix}{key}: section missing from {type(model).__name__}")
                    else:
                        walk(prefix + key + ".", value, sub)
                elif not hasattr(model, key):
                    drift.append(
                        f"{prefix}{key}={value!r}: field missing from {type(model).__name__}"
                    )

        walk("", yml, cfg)
        assert drift == [], f"YAML keys silently dropped by AppConfig: {drift}"


class TestConfigIO:
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test_config.yaml"
            cfg = AppConfig()
            save_config(cfg, str(path))
            loaded = load_config(str(path))
            assert loaded.data.exchange == cfg.data.exchange
            assert loaded.risk.position_limit_pct == cfg.risk.position_limit_pct

    def test_load_missing_file(self):
        cfg = load_config("/nonexistent/path.yaml")
        assert isinstance(cfg, AppConfig)
        assert cfg.data.exchange == "okx"

    def test_load_config_applies_yaml_env_and_cli_priority(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "priority.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "data": {"exchange": "binance", "sandbox": False},
                        "risk": {"max_drawdown": -0.05},
                    }
                ),
                encoding="utf-8",
            )
            monkeypatch.setenv("QUANTFLOW_DATA__SANDBOX", "true")
            monkeypatch.setenv("QUANTFLOW_RISK__MAX_DRAWDOWN", "-0.12")

            cfg = load_config(
                path,
                cli_overrides={"data": {"exchange": "okx-cli"}, "risk": {"max_drawdown": -0.2}},
            )

            assert cfg.data.exchange == "okx-cli"
            assert cfg.data.sandbox is True
            assert cfg.risk.max_drawdown == -0.2

    def test_save_config_can_keep_sensitive_fields_when_unsanitized(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "raw_config.yaml"
            cfg = AppConfig(
                monitoring=MonitoringConfig(
                    alert_channels=[
                        AlertChannelConfig(type="telegram", chat_id="c1", token="secret-token")
                    ]
                )
            )
            save_config(cfg, path, sanitize=False)

            raw = yaml.safe_load(path.read_text(encoding="utf-8"))

            assert raw["monitoring"]["alert_channels"][0]["token"] == "secret-token"


class TestConfigHelpers:
    def test_parse_env_value_covers_bool_int_float_and_string(self):
        assert _parse_env_value("true") is True
        assert _parse_env_value("0") is False
        assert _parse_env_value("123") == 123
        assert _parse_env_value("12.5") == 12.5
        assert _parse_env_value("BTC/USDT") == "BTC/USDT"

    def test_set_nested_and_deep_merge(self):
        nested: dict[str, object] = {}
        _set_nested(nested, ["risk", "limits", "max_drawdown"], -0.1)

        merged = _deep_merge(
            {"risk": {"limits": {"daily": -0.03}, "kill_switch_enabled": True}},
            nested,
        )

        assert nested == {"risk": {"limits": {"max_drawdown": -0.1}}}
        assert merged["risk"]["limits"]["daily"] == -0.03
        assert merged["risk"]["limits"]["max_drawdown"] == -0.1
        assert merged["risk"]["kill_switch_enabled"] is True

    def test_load_env_overrides_builds_nested_config(self, monkeypatch):
        monkeypatch.setenv("QUANTFLOW_EXECUTION__MODE", "live")
        monkeypatch.setenv("QUANTFLOW_DATA__RATE_LIMIT", "25")
        monkeypatch.setenv("QUANTFLOW_MONITORING__PROMETHEUS_PORT", "9100")

        overrides = _load_env_overrides()

        assert overrides["execution"]["mode"] == "live"
        assert overrides["data"]["rate_limit"] == 25
        assert overrides["monitoring"]["prometheus_port"] == 9100

    def test_sanitize_config_redacts_nested_sensitive_fields(self):
        sanitized = _sanitize_config(
            {
                "api_key": "top-secret",
                "monitoring": {
                    "alert_channels": [{"token": "abc", "chat_id": "c1"}],
                    "webhook": {"password": "pw"},
                },
                "safe": "value",
            }
        )

        assert sanitized["api_key"] == "***REDACTED***"
        assert sanitized["monitoring"]["alert_channels"][0]["token"] == "***REDACTED***"
        assert sanitized["monitoring"]["webhook"]["password"] == "***REDACTED***"
        assert sanitized["safe"] == "value"

    def test_resolve_config_path_maps_default_aliases_to_packaged_default(self):
        resolved = resolve_config_path("config/default.yaml")

        assert resolved.exists()
        assert resolved.as_posix().endswith("quantflow/config/default.yaml")

    def test_resolve_config_path_defaults_when_config_is_none(self):
        resolved = resolve_config_path()

        assert resolved.exists()
        assert resolved.name == "default.yaml"

    def test_resolve_config_path_prefers_existing_explicit_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "custom.yaml"
            path.write_text("data:\n  exchange: okx\n", encoding="utf-8")

            resolved = resolve_config_path(path)

            assert resolved == path

    def test_resolve_config_path_falls_back_to_package_relative_file(self):
        resolved = resolve_config_path("config/strategies/trend_following.yaml")

        assert resolved.exists()
        assert resolved.as_posix().endswith("quantflow/config/strategies/trend_following.yaml")
