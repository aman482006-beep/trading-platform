from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from live_runner.preflight import _parse_bool_env, run_live_preflight


def _write_config(path: Path, content: str) -> Path:
    path.write_text(dedent(content).strip() + "\n", encoding="utf-8")
    return path


# ─── strict boolean parsing (CTRADER_DEMO must never implicitly select live) ──


def test_parse_bool_env_missing_defaults_to_demo() -> None:
    # Missing CTRADER_DEMO must stay True (demo), never implicitly live.
    assert _parse_bool_env("CTRADER_DEMO", None, default=True) is True


@pytest.mark.parametrize(
    "value,expected",
    [
        ("true", True),
        ("True", True),
        ("  TRUE ", True),
        ("1", True),
        ("yes", True),
        ("y", True),
        ("on", True),
        ("false", False),
        ("False", False),
        ("0", False),
        ("no", False),
        ("n", False),
        ("off", False),
    ],
)
def test_parse_bool_env_recognized_tokens(value: str, expected: bool) -> None:
    assert _parse_bool_env("CTRADER_DEMO", value, default=True) is expected


@pytest.mark.parametrize("value", ["tru", "flase", "", "   ", "maybe", "2"])
def test_parse_bool_env_garbage_raises_naming_var_and_valid_values(value: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        _parse_bool_env("CTRADER_DEMO", value, default=True)
    message = str(excinfo.value)
    assert "CTRADER_DEMO" in message
    assert "true" in message
    assert "false" in message


def test_live_preflight_passes_for_demo_and_paper_accounts(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "live_deployments.yaml",
        """
        accounts:
          - id: alpaca-paper
            broker: alpaca
            broker_login: PA3EFBL4P7BU
          - id: "10105152"
            broker: ctrader

        deployments:
          - strategy_name: equity_momentum
            account_id: alpaca-paper
            symbols: [AAPL]
            timeframe: 1h
          - strategy_name: fx_breakout
            account_id: "10105152"
            symbols: [EURUSD]
            timeframe: 15m
        """,
    )

    result = run_live_preflight(
        config_path,
        env={
            "ALPACA_API_KEY_ACC1": "alpaca-key",
            "ALPACA_SECRET_KEY_ACC1": "alpaca-secret",
            "ALPACA_ACCOUNT_NUMBER_ACC1": "PA3EFBL4P7BU",
            "ALPACA_ENDPOINT_ACC1": "https://paper-api.alpaca.markets/v2",
            "CTRADER_APP_ID": "app",
            "CTRADER_APP_SECRET": "secret",
            "CTRADER_ACCESS_TOKEN": "token",
            "CTRADER_REFRESH_TOKEN": "refresh",
            "CTRADER_DEMO": "true",
        },
    )

    assert result.ok is True
    assert [account.ok for account in result.accounts] == [True, True]
    assert result.deployment_errors == []


def test_live_preflight_reports_missing_credentials(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "live_deployments.yaml",
        """
        accounts:
          - id: alpaca-paper
            broker: alpaca

        deployments:
          - strategy_name: equity_momentum
            account_id: alpaca-paper
            symbols: [AAPL]
            timeframe: 1h
        """,
    )

    result = run_live_preflight(config_path, env={})

    assert result.ok is False
    assert result.accounts[0].ok is False
    assert "Missing Alpaca credentials" in result.accounts[0].errors[0]


def test_live_preflight_rejects_non_numeric_ctrader_account_id(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "live_deployments.yaml",
        """
        accounts:
          - id: ctrader-demo
            broker: ctrader

        deployments:
          - strategy_name: fx_breakout
            account_id: ctrader-demo
            symbols: [EURUSD]
            timeframe: 15m
        """,
    )

    result = run_live_preflight(
        config_path,
        env={
            "CTRADER_APP_ID": "app",
            "CTRADER_APP_SECRET": "secret",
            "CTRADER_ACCESS_TOKEN": "token",
        },
    )

    # B3: unroutable accounts fail the preflight as a reported config
    # error, not an unhandled crash.
    assert result.ok is False
    assert any(
        "no numeric broker identifier" in error for error in result.deployment_errors
    )


def test_live_preflight_reports_unknown_deployment_account(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "live_deployments.yaml",
        """
        accounts:
          - id: alpaca-paper
            broker: alpaca

        deployments:
          - strategy_name: orphan_strategy
            account_id: missing-account
            symbols: [AAPL]
            timeframe: 1h
        """,
    )

    result = run_live_preflight(
        config_path,
        env={
            "ALPACA_API_KEY": "alpaca-key",
            "ALPACA_SECRET_KEY": "alpaca-secret",
            "ALPACA_PAPER": "true",
        },
    )

    assert result.ok is False
    assert result.deployment_errors == [
        "orphan_strategy (missing-account): references unknown account_id."
    ]



def test_live_preflight_connectivity_reads_alpaca_balance_and_positions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = _write_config(
        tmp_path / "live_deployments.yaml",
        """
        accounts:
          - id: alpaca-paper
            broker: alpaca

        deployments:
          - strategy_name: equity_momentum
            account_id: alpaca-paper
            symbols: [AAPL]
            timeframe: 1h
        """,
    )

    class _FakeAlpacaAdapter:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def connect(self):
            return None

        async def get_balance(self):
            return 1234.5, 2345.6

        async def get_positions(self):
            return [{"symbol": "AAPL"}, {"symbol": "MSFT"}]

        async def disconnect(self):
            return None

    from live_runner import preflight

    monkeypatch.setattr(preflight, "AlpacaLiveAdapter", _FakeAlpacaAdapter)

    result = run_live_preflight(
        config_path,
        env={
            "ALPACA_API_KEY": "alpaca-key",
            "ALPACA_SECRET_KEY": "alpaca-secret",
            "ALPACA_PAPER": "true",
        },
        check_connectivity=True,
    )

    assert result.ok is True
    assert result.accounts[0].connected is True
    assert result.accounts[0].balance == 1234.5
    assert result.accounts[0].equity == 2345.6
    assert result.accounts[0].positions_count == 2


def test_live_preflight_connectivity_reports_ctrader_error(tmp_path: Path, monkeypatch) -> None:
    config_path = _write_config(
        tmp_path / "live_deployments.yaml",
        """
        accounts:
          - id: "10105152"
            broker: ctrader

        deployments:
          - strategy_name: fx_breakout
            account_id: "10105152"
            symbols: [EURUSD]
            timeframe: 15m
        """,
    )

    class _FakeCTraderAdapter:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def connect(self):
            raise RuntimeError("auth failed")

        async def disconnect(self):
            return None

    from live_runner import preflight

    monkeypatch.setattr(preflight, "CTraderLiveAdapter", _FakeCTraderAdapter)

    result = run_live_preflight(
        config_path,
        env={
            "CTRADER_APP_ID": "app",
            "CTRADER_APP_SECRET": "secret",
            "CTRADER_ACCESS_TOKEN": "token",
            "CTRADER_REFRESH_TOKEN": "refresh",
        },
        check_connectivity=True,
    )

    assert result.ok is False
    assert result.accounts[0].connected is False
    assert "cTrader connectivity check failed" in result.accounts[0].errors[0]


def test_live_preflight_threads_accounts_env_path_to_ctrader_adapter(
    tmp_path: Path, monkeypatch
) -> None:
    """Preflight must construct the cTrader adapter with the validated accounts file.

    The adapter's token refresh must read & write exactly that file; the default
    .accounts.env must be left untouched.
    """
    config_path = _write_config(
        tmp_path / "live_deployments.yaml",
        """
        accounts:
          - id: "10105152"
            broker: ctrader

        deployments:
          - strategy_name: fx_breakout
            account_id: "10105152"
            symbols: [EURUSD]
            timeframe: 15m
        """,
    )

    accounts_env = tmp_path / "custom.accounts.env"
    accounts_env.write_text(
        "CTRADER_ACCESS_TOKEN=old-access\nCTRADER_REFRESH_TOKEN=old-refresh\n",
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    class _FakeCTraderAdapter:
        def __init__(self, **kwargs):
            captured["accounts_env_path"] = kwargs.get("accounts_env_path")
            self._path = Path(kwargs["accounts_env_path"])

        async def connect(self):
            # Simulate a token refresh writing to exactly the threaded file.
            self._path.write_text(
                "CTRADER_ACCESS_TOKEN=new-access\nCTRADER_REFRESH_TOKEN=new-refresh\n",
                encoding="utf-8",
            )

        async def get_balance(self):
            return 100.0, 100.0

        async def get_positions(self):
            return []

        async def disconnect(self):
            return None

    from live_runner import preflight

    monkeypatch.setattr(preflight, "CTraderLiveAdapter", _FakeCTraderAdapter)

    # Ensure the default accounts file would be detectable if wrongly written.
    default_path = Path(preflight.DEFAULT_ACCOUNTS_ENV)
    default_before = default_path.read_text(encoding="utf-8") if default_path.exists() else None

    result = run_live_preflight(
        config_path,
        accounts_env_path=accounts_env,
        env={
            "CTRADER_APP_ID": "app",
            "CTRADER_APP_SECRET": "secret",
            "CTRADER_ACCESS_TOKEN": "old-access",
            "CTRADER_REFRESH_TOKEN": "old-refresh",
            "CTRADER_DEMO": "true",
        },
        check_connectivity=True,
    )

    assert result.ok is True
    # Adapter received exactly the validated/threaded path.
    assert Path(str(captured["accounts_env_path"])) == accounts_env
    # The threaded file was refreshed in place.
    assert "new-access" in accounts_env.read_text(encoding="utf-8")
    # The default .accounts.env must be untouched.
    default_after = default_path.read_text(encoding="utf-8") if default_path.exists() else None
    assert default_after == default_before


# ─── ${VAR} expansion honours --accounts-env (#184 finding 6) ───────────────────


_ENV_REF_CONFIG = """
    accounts:
      - id: alpaca-paper
        broker: alpaca

    deployments:
      - strategy_name: discord_follow
        account_id: alpaca-paper
        symbols: [AAPL]
        timeframe: 1h
        signal_source: discord
        signal_config:
          channel_id: "${PREFLIGHT_TEST_CHANNEL_ID}"
    """


def test_live_preflight_expands_config_refs_from_accounts_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PREFLIGHT_TEST_CHANNEL_ID", raising=False)
    config_path = _write_config(tmp_path / "live_deployments.yaml", _ENV_REF_CONFIG)
    accounts_env = tmp_path / ".accounts.env"
    accounts_env.write_text("PREFLIGHT_TEST_CHANNEL_ID=123456\n", encoding="utf-8")

    result = run_live_preflight(config_path, accounts_env_path=accounts_env)

    assert not any("PREFLIGHT_TEST_CHANNEL_ID" in err for err in result.deployment_errors)
    assert not any("unexpanded" in err.lower() for err in result.deployment_errors)


def test_live_preflight_accounts_env_file_wins_over_process_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Same file-first precedence as credentials (resolve_env_value).
    monkeypatch.setenv("PREFLIGHT_TEST_CHANNEL_ID", "from-process")
    config_path = _write_config(tmp_path / "live_deployments.yaml", _ENV_REF_CONFIG)
    accounts_env = tmp_path / ".accounts.env"
    accounts_env.write_text("PREFLIGHT_TEST_CHANNEL_ID=from-file\n", encoding="utf-8")
    seen: dict[str, object] = {}

    import live_runner.preflight as preflight

    real = preflight.parse_live_deployments_config

    def spy(path, *, env_values=None):
        accounts, deployments = real(path, env_values=env_values)
        seen["channel"] = deployments[0].signal_config["channel_id"]
        return accounts, deployments

    monkeypatch.setattr(preflight, "parse_live_deployments_config", spy)
    run_live_preflight(config_path, accounts_env_path=accounts_env)

    assert seen["channel"] == "from-file"


def test_live_preflight_still_expands_from_process_env_without_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PREFLIGHT_TEST_CHANNEL_ID", "777")
    config_path = _write_config(tmp_path / "live_deployments.yaml", _ENV_REF_CONFIG)

    result = run_live_preflight(
        config_path, accounts_env_path=tmp_path / "missing.accounts.env"
    )

    assert not any("PREFLIGHT_TEST_CHANNEL_ID" in err for err in result.deployment_errors)


def test_live_preflight_unset_config_ref_is_still_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PREFLIGHT_TEST_CHANNEL_ID", raising=False)
    config_path = _write_config(tmp_path / "live_deployments.yaml", _ENV_REF_CONFIG)

    result = run_live_preflight(
        config_path, accounts_env_path=tmp_path / "missing.accounts.env"
    )

    assert result.ok is False
    assert any("PREFLIGHT_TEST_CHANNEL_ID" in err for err in result.deployment_errors)


def test_live_preflight_explicit_env_mapping_is_not_merged_with_process_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit ``env=`` mapping is used as-is: a hermetic caller passing
    ``env={}`` to prove an unset reference fails must not have that reference
    silently expanded from whatever the runner's process environment happens to
    define - the preflight is the gate before live orders are enabled."""
    monkeypatch.setenv("PREFLIGHT_TEST_CHANNEL_ID", "from-process")
    config_path = _write_config(tmp_path / "live_deployments.yaml", _ENV_REF_CONFIG)

    result = run_live_preflight(config_path, env={})

    assert result.ok is False
    assert any("PREFLIGHT_TEST_CHANNEL_ID" in err for err in result.deployment_errors)


def test_live_preflight_empty_file_value_wins_over_process_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A present-but-empty file key shadows the process environment during
    ${VAR} expansion, exactly like ``resolve_env_value`` does for credentials:
    a key an operator blanked to disable/invalidate it must not silently fall
    back to a stale process-env value."""
    monkeypatch.setenv("PREFLIGHT_TEST_CHANNEL_ID", "from-process")
    config_path = _write_config(tmp_path / "live_deployments.yaml", _ENV_REF_CONFIG)
    accounts_env = tmp_path / ".accounts.env"
    accounts_env.write_text("PREFLIGHT_TEST_CHANNEL_ID=\n", encoding="utf-8")
    seen: dict[str, object] = {}

    import live_runner.preflight as preflight

    real = preflight.parse_live_deployments_config

    def spy(path, *, env_values=None):
        accounts, deployments = real(path, env_values=env_values)
        seen["channel"] = deployments[0].signal_config["channel_id"]
        return accounts, deployments

    monkeypatch.setattr(preflight, "parse_live_deployments_config", spy)
    run_live_preflight(config_path, accounts_env_path=accounts_env)

    assert seen["channel"] == ""


def test_live_preflight_unreadable_accounts_env_reports_failure_not_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A present-but-unreadable accounts env file is a config error, not a crash.

    Every other accounts-env read in live_runner goes through
    ``load_accounts_env_values``, which warns and continues with the process
    environment; preflight must not raise an unhandled OSError traceback just
    because the YAML parse now reads the same file.
    """
    import live_runner.credential_env as credential_env
    import live_runner.preflight as preflight

    config_path = _write_config(
        tmp_path / "live_deployments.yaml",
        """
        accounts:
          - id: alpaca-paper
            broker: alpaca

        deployments:
          - strategy_name: equity_momentum
            account_id: alpaca-paper
            symbols: [AAPL]
            timeframe: 1h
        """,
    )
    accounts_env = tmp_path / ".accounts.env"
    accounts_env.write_text("ALPACA_API_KEY=file-key\n", encoding="utf-8")

    def _deny(_path: object) -> dict[str, str]:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(preflight, "dotenv_values", _deny, raising=False)
    monkeypatch.setattr(credential_env, "dotenv_values", _deny)

    result = run_live_preflight(config_path, accounts_env_path=accounts_env)

    assert result.ok is False
    assert any("Missing Alpaca credentials" in e for e in result.accounts[0].errors)
