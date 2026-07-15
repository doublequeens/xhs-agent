# Claude Code Instructions

开始任何工作前必须先完整阅读根目录 `AGENTS.md`；`AGENTS.md` 是权威规则，本文只提供 Claude Code 入口摘要。

- 项目使用 Python 3.12，默认验证命令为 `pytest -q`，完成前还应运行 `python -m compileall -q src main.py` 和 `git diff --check`。
- 人类使用说明见 [`README.md`](README.md)，文档索引见 [`docs/README.md`](docs/README.md)。
- 修改前保护用户已有改动、SQLite/checkpoint、`outputs/publish` 和 `~/.xhs-agent` 状态。
- 不要擅自 push、reset、删除状态数据库、覆盖已验证输出或提交密钥/私有文件。
- 不要绕过 QA、Human Review、Final Guard 或现代 schema；不要恢复已删除的旧生产路径。
- 只有新鲜验证证据支持时，才能声称任务完成或测试通过。
