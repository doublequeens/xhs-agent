# Trend Collector

Run commands from the repository root.

Install the LaunchAgent:

```bash
python -m trend_collector install-launchagent
```

Then run the printed `launchctl bootstrap ...` command.

By default, the LaunchAgent runs daily at 22:30 in the macOS system local time.

The collector reuses `~/.xhs-agent/browser-profile`, writes logs to
`~/.xhs-agent/logs/trend_collector.out.log` and
`~/.xhs-agent/logs/trend_collector.err.log`, and stores normalized signals in
`data/xhs_memory.db`.

The collector reads creator-center trend surfaces only. It does not open note
details, publish, comment, like, follow, search, or paginate aggressively.
