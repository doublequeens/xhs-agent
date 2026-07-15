# 趋势信号采集器操作手册

趋势采集器从小红书创作者中心的灵感/活动趋势页面读取信号，写入本地记忆，供选题信号节点使用。它不是发布器，也不负责打开笔记详情或执行互动。

## CLI 命令

从仓库根目录运行 `python -m trend_collector --help` 可查看入口。支持：

```bash
python -m trend_collector collect
python -m trend_collector install-launchagent
```

`collect` 执行一次采集并打印 `status` 与 `collected_signals`；成功或已跳过时退出码为 0。默认使用 `~/.xhs-agent/browser-profile`，写入 `data/xhs_memory.db`，并使用 `memory/schema.sql` 初始化所需表。

当前配置包含美妆、时尚、知识等灵感分类，每个区块最多读取 20 条；采集器的内部默认 target domain 是 `healthy_lifestyle/daily_habits`，这只是趋势信号的技术归档，不改变账号正式的 beauty/skincare 定位。

## 安装每日 LaunchAgent

```bash
python -m trend_collector install-launchagent
```

安装器写入 `~/Library/LaunchAgents/com.xhs-agent.trend-collector.plist`，安排每天 22:30（`Asia/Shanghai`）执行，并打印 `launchctl bootstrap` 命令。它不会替你执行 bootstrap；手动运行：

```bash
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.xhs-agent.trend-collector.plist
launchctl print gui/$UID/com.xhs-agent.trend-collector
launchctl bootout gui/$UID/com.xhs-agent.trend-collector
rm ~/Library/LaunchAgents/com.xhs-agent.trend-collector.plist
```

Trend LaunchAgent 使用独立的输出和错误日志：

- `~/.xhs-agent/logs/trend_collector.out.log`
- `~/.xhs-agent/logs/trend_collector.err.log`

状态目录、profile、日志和 LaunchAgent plist 都属于本机配置，不提交到仓库。需要变更 Python 或仓库路径时，先 bootout 旧 plist，再重新安装并 bootstrap。

## 访问边界与故障排查

采集器只访问 creator-center 的趋势/灵感 surface（包括配置中的 inspiration 与 events 页面），不打开笔记详情，不发布、不评论、不点赞、不关注、不搜索，也不进行激进翻页。采集失败时先查看 namespaced 日志和命令摘要，再检查 `data/xhs_memory.db` 是否有新信号；不要通过删除数据库来掩盖失败。
