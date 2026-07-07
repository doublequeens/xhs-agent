import os
import plistlib
from pathlib import Path

from metrics_collector.launchd import (
    build_launchagent_payload as build_metrics_payload,
    install_launchagent,
)
from trend_collector.launchd import (
    LABEL,
    build_launchagent_payload,
    install_trend_launchagent,
)


def _trend_payload(*, log_dir):
    return build_launchagent_payload(
        python_path=Path("/usr/bin/python3"),
        repo_root=Path("/repo"),
        log_dir=log_dir,
    )


def test_trend_collector_launchagent_payload():
    payload = build_launchagent_payload(
        python_path=Path("/usr/bin/python3"),
        repo_root=Path("/repo"),
        log_dir=Path("/Users/example/.xhs-agent/logs"),
    )

    assert LABEL == "com.xhs-agent.trend-collector"
    assert payload["ProgramArguments"] == [
        "/usr/bin/python3",
        "-m",
        "trend_collector",
        "collect",
    ]
    assert payload["StartCalendarInterval"] == {"Hour": 22, "Minute": 30}


def test_payload_has_full_shape_with_separate_logs_and_no_runatload():
    """Full payload contract: scheduled (RunAtLoad False, unlike metrics
    which is RunAtLoad True), Background process, repo WorkingDirectory, and
    log filenames namespaced to trend_collector (separate from metrics)."""
    payload = build_launchagent_payload(
        python_path=Path("/usr/bin/python3"),
        repo_root=Path("/repo"),
        log_dir=Path("/Users/example/.xhs-agent/logs"),
    )

    assert payload["Label"] == "com.xhs-agent.trend-collector"
    assert payload["WorkingDirectory"] == "/repo"
    assert payload["RunAtLoad"] is False
    assert payload["ProcessType"] == "Background"
    assert payload["StandardOutPath"] == "/Users/example/.xhs-agent/logs/trend_collector.out.log"
    assert payload["StandardErrorPath"] == "/Users/example/.xhs-agent/logs/trend_collector.err.log"
    # namespaced away from metrics collector's log filenames
    assert payload["StandardOutPath"].endswith("trend_collector.out.log")
    assert payload["StandardOutPath"] != build_metrics_payload(
        python_path=Path("/usr/bin/python3"),
        repo_root=Path("/repo"),
        log_dir=Path("/Users/example/.xhs-agent/logs"),
    )["StandardOutPath"]


def test_install_trend_launchagent_uses_trend_label_filename(tmp_path):
    payload = _trend_payload(log_dir=tmp_path / ".xhs-agent" / "logs")
    plist_path = install_trend_launchagent(payload, tmp_path)

    assert plist_path.name == "com.xhs-agent.trend-collector.plist"
    assert plist_path.parent == tmp_path / "Library" / "LaunchAgents"


def test_installed_plist_carries_trend_label_and_secure_mode(tmp_path):
    """The written plist's CONTENT (not just filename) must carry the trend
    label and program, and the file must be 0o600."""
    payload = _trend_payload(log_dir=tmp_path / ".xhs-agent" / "logs")
    plist_path = install_trend_launchagent(payload, tmp_path)

    data = plistlib.loads(plist_path.read_bytes())
    assert data["Label"] == "com.xhs-agent.trend-collector"
    assert data["ProgramArguments"] == ["/usr/bin/python3", "-m", "trend_collector", "collect"]
    assert data["StartCalendarInterval"] == {"Hour": 22, "Minute": 30}
    assert (plist_path.stat().st_mode & 0o777) == 0o600


def test_trend_and_metrics_plists_coexist_without_collision(tmp_path):
    """The collision fix: trend and metrics LaunchAgents installed in the
    same home coexist as two distinct plist files, each carrying its own
    label. Under the old module-constant filename this would have silently
    overwritten the metrics plist."""
    log_dir = tmp_path / ".xhs-agent" / "logs"
    metrics_payload = build_metrics_payload(
        python_path=Path("/usr/bin/python3"),
        repo_root=Path("/repo"),
        log_dir=log_dir,
    )
    trend_payload = _trend_payload(log_dir=log_dir)

    metrics_path = install_launchagent(metrics_payload, tmp_path)
    trend_path = install_trend_launchagent(trend_payload, tmp_path)

    assert metrics_path.name == "com.xhs-agent.metrics-collector.plist"
    assert trend_path.name == "com.xhs-agent.trend-collector.plist"
    assert metrics_path != trend_path
    assert metrics_path.exists() and trend_path.exists()
    # installing trend did NOT corrupt the metrics plist's label
    assert plistlib.loads(metrics_path.read_bytes())["Label"] == "com.xhs-agent.metrics-collector"
    assert plistlib.loads(trend_path.read_bytes())["Label"] == "com.xhs-agent.trend-collector"


def test_install_is_idempotent(tmp_path):
    """Re-installing overwrites the same plist in place; no leftover temp or
    duplicate files."""
    payload = _trend_payload(log_dir=tmp_path / ".xhs-agent" / "logs")
    first = install_trend_launchagent(payload, tmp_path)
    second = install_trend_launchagent(payload, tmp_path)

    assert first == second
    launchagents = tmp_path / "Library" / "LaunchAgents"
    plists = [p for p in launchagents.iterdir() if p.name.endswith(".plist")]
    assert [p.name for p in plists] == ["com.xhs-agent.trend-collector.plist"]


def test_install_launchagent_cli_prints_bootstrap_command(tmp_path, monkeypatch, capsys):
    """The install-launchagent CLI builds the payload from sys.executable +
    repo root, installs into the user home, and prints the launchctl
    bootstrap command pointing at the trend plist."""
    import trend_collector.__main__ as cli

    monkeypatch.setattr("trend_collector.__main__.Path.home", lambda: tmp_path)

    rc = cli.main(["install-launchagent"])
    out = capsys.readouterr().out.strip()

    assert rc == 0
    assert out.startswith("launchctl bootstrap ")
    assert f"gui/{os.getuid()}" in out
    assert out.endswith("com.xhs-agent.trend-collector.plist")
    # the plist was actually installed under the (patched) home
    assert (tmp_path / "Library" / "LaunchAgents" / "com.xhs-agent.trend-collector.plist").exists()
