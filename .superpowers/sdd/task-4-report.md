# Task 4 report

## Status

DONE

## Delivered

- 重写 `AGENTS.md`，保留 GitHub Issues、triage labels 和 domain docs 规则，并加入产品定位、现代单一路径、核心契约、验证、状态/素材安全和文档索引。
- 重写精简 `CLAUDE.md`，要求先读 AGENTS，链接 README/docs 索引，声明默认验证命令和状态/Git 安全边界。

## Verification

- `rg -n "TBD|TODO|占位|待定|/Users/|sk-[A-Za-z0-9]|AIza" AGENTS.md CLAUDE.md || true`：无匹配。
- 必需索引链接扫描：issue-tracker、triage-labels、agents/domain、docs/README、architecture 均存在。
- `git diff --check`：通过。
