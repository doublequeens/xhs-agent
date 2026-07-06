# Metrics Collector Operations

Run all commands from the repository root. The collector uses a dedicated
browser profile under `~/.xhs-agent`.

## Setup and authentication

```bash
pip install -r requirements.txt
playwright install chromium
python -m metrics_collector auth
```

Complete the Xiaohongshu login in the opened browser and press Enter only after
the creator data page loads successfully.

Run a manual smoke collection before scheduling:

```bash
python -m metrics_collector collect
```

Automated tests never access Xiaohongshu or any other live network service.

## Install the daily LaunchAgent

```bash
python -m metrics_collector install-launchagent
```

This writes
`~/Library/LaunchAgents/com.xhs-agent.metrics-collector.plist`, schedules a
collection at 22:00 and at login, and prints the exact bootstrap command. It
does not run `launchctl` and never requires `sudo`.

Load, inspect, and remove the agent with:

```bash
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.xhs-agent.metrics-collector.plist
launchctl print gui/$UID/com.xhs-agent.metrics-collector
launchctl bootout gui/$UID/com.xhs-agent.metrics-collector
rm ~/Library/LaunchAgents/com.xhs-agent.metrics-collector.plist
```

Re-run `install-launchagent` after changing the repository location or Python
environment, then boot out and bootstrap the agent again.

## Recovery and diagnostics

If a run reports `status=auth_required`, the saved login has expired. Run
`python -m metrics_collector auth`, complete login again, and then run
`python -m metrics_collector collect` to verify recovery. The next scheduled
run will use the refreshed profile.

Standard output and errors are written to
`~/.xhs-agent/logs/collector.out.log` and
`~/.xhs-agent/logs/collector.err.log`. Workbooks that fail validation are
preserved in `~/.xhs-agent/diagnostics`; diagnostic workbooks are retained for
7 days.
