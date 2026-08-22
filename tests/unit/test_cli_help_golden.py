"""REV-009/P1: freeze the CLI surface before the commands-package split.

Locks ``quantflow --help`` command order (Typer preserves registration order,
typer>=0.25 list_commands) and every subcommand's ``--help`` exit status, so the
P4 repackaging cannot drift the public contract.
"""

from __future__ import annotations

from typer.testing import CliRunner

from quantflow.cli.main import app

runner = CliRunner()

#: Exact top-level command order as of REV-009 (pre-split baseline).
COMMANDS_EXPECTED: tuple[str, ...] = (
    "download",
    "download-funding",
    "download-oi",
    "download-binance",
    "download-bybit",
    "download-bybit-funding",
    "download-bybit-oi",
    "research",
    "optimize",
    "validate",
    "run",
    "benchmark",
    "station",
    "ai",
    "new-strategy",
    "assert-elliott",
    "freeze-b4",
    "eval-btc-overlay",
    "kol-ingest",
    "status",
)


def _registered_command_names() -> list[str]:
    """Command names in registration order (Typer preserves insertion order).

    ``registered_commands`` carries the callback name; explicit-name commands
    expose it via ``name`` while decorator-inferred names resolve from the
    function, so fall back through info objects.
    """
    names: list[str] = []
    for cmd in app.registered_commands:
        name = cmd.name
        if name is None and cmd.callback is not None:
            name = (cmd.callback.__name__ or "").replace("_", "-")
        names.append(name or "")
    return names



def test_top_level_registration_order() -> None:
    names = _registered_command_names()
    assert tuple(names) == COMMANDS_EXPECTED


def test_each_subcommand_help_exits_zero() -> None:
    for cmd in COMMANDS_EXPECTED:
        result = runner.invoke(app, [cmd, "--help"])
        assert result.exit_code == 0, f"{cmd} --help failed: {result.output}"
