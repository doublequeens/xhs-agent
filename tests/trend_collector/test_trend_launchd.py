from pathlib import Path

from trend_collector.launchd import LABEL, build_launchagent_payload


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
    assert payload["StartCalendarInterval"] == {"Hour": 16, "Minute": 30}


def test_install_trend_launchagent_uses_trend_label_filename(tmp_path):
    from trend_collector.launchd import build_launchagent_payload, install_trend_launchagent

    payload = build_launchagent_payload(
        python_path=Path("/usr/bin/python3"),
        repo_root=Path("/repo"),
        log_dir=tmp_path / ".xhs-agent" / "logs",
    )
    plist_path = install_trend_launchagent(payload, tmp_path)

    assert plist_path.name == "com.xhs-agent.trend-collector.plist"
    assert plist_path.parent == tmp_path / "Library" / "LaunchAgents"
