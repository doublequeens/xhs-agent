import os
import plistlib
import sys
from pathlib import Path

import pytest

from metrics_collector.launchd import (
    LABEL,
    build_launchagent_payload,
    install_launchagent,
)


def test_payload_runs_collect_at_2200_and_at_load(tmp_path):
    python_path = tmp_path / "venv" / "bin" / "python"
    repo_root = tmp_path / "repo"
    log_dir = tmp_path / "logs"

    payload = build_launchagent_payload(python_path, repo_root, log_dir)

    assert payload == {
        "Label": "com.xhs-agent.metrics-collector",
        "ProgramArguments": [
            str(python_path),
            "-m",
            "metrics_collector",
            "collect",
        ],
        "WorkingDirectory": str(repo_root),
        "StartCalendarInterval": {"Hour": 22, "Minute": 0},
        "RunAtLoad": True,
        "ProcessType": "Background",
        "StandardOutPath": str(log_dir / "collector.out.log"),
        "StandardErrorPath": str(log_dir / "collector.err.log"),
    }


def test_install_writes_only_user_launchagents_and_valid_plist(tmp_path):
    user_home = tmp_path / "home"
    log_dir = user_home / ".xhs-agent" / "logs"
    payload = build_launchagent_payload(
        Path("/usr/bin/python3"), tmp_path / "repo", log_dir
    )

    plist_path = install_launchagent(payload, user_home)

    expected = (
        user_home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    )
    assert plist_path == expected
    assert list(tmp_path.rglob("*.plist")) == [expected]
    with expected.open("rb") as plist_file:
        assert plistlib.load(plist_file) == payload
    assert log_dir.stat().st_mode & 0o777 == 0o700


def test_install_corrects_existing_log_directory_permissions(tmp_path):
    user_home = tmp_path / "home"
    log_dir = user_home / ".xhs-agent" / "logs"
    log_dir.mkdir(parents=True, mode=0o755)
    log_dir.chmod(0o755)
    payload = build_launchagent_payload(
        Path("/usr/bin/python3"), tmp_path / "repo", log_dir
    )

    install_launchagent(payload, user_home)

    assert log_dir.stat().st_mode & 0o777 == 0o700


def test_install_refuses_symlink_plist_target(tmp_path):
    user_home = tmp_path / "home"
    launchagents = user_home / "Library" / "LaunchAgents"
    launchagents.mkdir(parents=True)
    target = launchagents / f"{LABEL}.plist"
    target.symlink_to(tmp_path / "elsewhere.plist")
    payload = build_launchagent_payload(
        Path("/usr/bin/python3"), tmp_path / "repo", tmp_path / "logs"
    )

    with pytest.raises(ValueError, match="symlink"):
        install_launchagent(payload, user_home)


def test_install_refuses_symlink_launchagents_directory(tmp_path):
    user_home = tmp_path / "home"
    library = user_home / "Library"
    library.mkdir(parents=True)
    (library / "LaunchAgents").symlink_to(
        tmp_path / "outside", target_is_directory=True
    )
    (tmp_path / "outside").mkdir()
    payload = build_launchagent_payload(
        Path("/usr/bin/python3"), tmp_path / "repo", tmp_path / "logs"
    )

    with pytest.raises(ValueError, match="symlink"):
        install_launchagent(payload, user_home)


def test_install_launchagent_cli_uses_current_python_and_prints_command(
    monkeypatch, tmp_path, capsys
):
    from metrics_collector import __main__ as cli

    home = tmp_path / "home"
    installed_path = (
        home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    )
    captured = {}

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(os, "getuid", lambda: 501)

    def fake_install(payload, user_home):
        captured["payload"] = payload
        captured["user_home"] = user_home
        return installed_path

    monkeypatch.setattr(cli, "install_launchagent", fake_install)

    assert cli.main(["install-launchagent"]) == 0

    assert captured["user_home"] == home
    assert captured["payload"]["ProgramArguments"][0] == sys.executable
    assert captured["payload"]["WorkingDirectory"] == str(
        Path(cli.__file__).resolve().parent.parent
    )
    assert captured["payload"]["StandardOutPath"] == str(
        home / ".xhs-agent" / "logs" / "collector.out.log"
    )
    assert capsys.readouterr().out == (
        f"launchctl bootstrap gui/501 {installed_path}\n"
    )
