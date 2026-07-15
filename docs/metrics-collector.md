# 指标采集器操作手册

所有命令从仓库根目录执行。采集器通过 Playwright 使用专用浏览器 profile，不复用日常浏览器会话。

## 安装与登录

```bash
pip install -r requirements.txt
playwright install chromium
brew install --cask google-chrome
python -m metrics_collector auth
```

采集器配置为 Playwright 的 `chrome` channel，因此除了执行 `playwright install chromium` 外，还需要本机安装 **Google Chrome**。已经安装 Chrome 时可跳过 Homebrew 命令。认证命令会打开专用浏览器；在其中手动完成小红书创作者中心登录，确认数据分析页面加载成功后再按 Enter。

默认状态目录为 `~/.xhs-agent`：

- 浏览器 profile：`~/.xhs-agent/browser-profile`
- 下载目录：`~/.xhs-agent/downloads`
- 校验失败的 workbook 诊断：`~/.xhs-agent/diagnostics`
- 日志：`~/.xhs-agent/logs/collector.out.log` 与 `~/.xhs-agent/logs/collector.err.log`

## CLI 命令

运行 `python -m metrics_collector --help` 可查看当前入口。支持三个子命令：

```bash
python -m metrics_collector auth       # 打开 profile，手动登录并验证
python -m metrics_collector collect    # 手动执行一次指标采集
python -m metrics_collector install-launchagent  # 安装每日 LaunchAgent
```

先做一次手动采集确认登录和数据格式：

```bash
python -m metrics_collector collect
```

采集结果会写入 `data/xhs_memory.db`，命令行摘要包含 status、scheduled/execution date、导出/更新/跳过/歧义行数和匹配到的 post ID 数。采集器只读取创作者中心的数据分析与笔记管理页面，不应把工作簿诊断文件当作已成功写回数据库的证据；故障排查时要同时核对运行摘要和数据库状态。

自动化测试默认不访问小红书或其他 live network service。

## 安装每日任务

```bash
python -m metrics_collector install-launchagent
```

安装器写入 `~/Library/LaunchAgents/com.xhs-agent.metrics-collector.plist`，安排每天 22:00 执行，并打印精确的 `launchctl bootstrap` 命令。它不会自动调用 `launchctl`，也不需要 `sudo`。`StartCalendarInterval` 使用 macOS 系统本地时区；系统时区必须是 `Asia/Shanghai`，安装器会在写入 plist 前验证。

手动加载、查看和卸载：

```bash
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.xhs-agent.metrics-collector.plist
launchctl print gui/$UID/com.xhs-agent.metrics-collector
launchctl bootout gui/$UID/com.xhs-agent.metrics-collector
rm ~/Library/LaunchAgents/com.xhs-agent.metrics-collector.plist
```

变更仓库路径或 Python 环境后，先 bootout 旧任务，再重新运行安装命令并 bootstrap 新 plist。

## 恢复与诊断

若摘要为 `status=auth_required`，说明保存的登录已过期：重新运行 `python -m metrics_collector auth`，完成手动登录后再运行 `collect`。后续 LaunchAgent 会继续使用更新后的 profile。

workbook 校验失败时，原文件会保留在 `~/.xhs-agent/diagnostics`，诊断文件默认保留 7 天。日志和诊断目录属于本机运行状态，不提交到 Git。
