# handoff.md

## 当前任务卡

- 任务：删除兼容层、旧产品面和重复测试，收敛到当前支持的 CLI
- 状态：`ready_to_merge`
- 当前 owner：Codex
- 分支：`cleanup/remove-redundant-surfaces`
- PR：[#28](https://github.com/apue/yt2notion/pull/28)
- review 状态：Spec / Standards 双轴复审均无剩余 findings
- 目标：
  - 保留 `process`、`prepare`、`transcribe`
  - 保留 Obsidian bundle、MediaSource、Transcriber、LLMCaller adapter
  - 删除 pipeline facade、legacy extract、文件队列 Agent、旧 Notion 单笔记路径
  - 统一 LLM note composition
- 非目标：
  - 不改变 ASR 状态机、artifact 契约或 prompt 模板
  - 不调用远程 ASR、LLM、Notion 或 Obsidian
- 验收标准：见 [docs/harness/ACCEPTANCE.md](./docs/harness/ACCEPTANCE.md)
- 验证：见 [docs/harness/VALIDATION_PLAN.md](./docs/harness/VALIDATION_PLAN.md)
- 已完成：
  - 删除 pipeline facade、legacy extract、文件队列 Agent、Notion 单笔记路径
  - 将 LLM note composition 收拢到 `NoteComposer`
  - 将存储接口收窄为 Obsidian `save_note_bundle`
  - 将 ASR 回归测试迁到 `TranscriptionEngine` 接口
  - 测试从 341 个降至 216 个，并保留 ASR quota/checkpoint/upload-budget 回归保护
  - Spec 审查发现 ASR 测试删减过度后，以 7 个接口级用例补回关键行为
  - 隔离 `ANTHROPIC_API_KEY`，避免 factory 测试受本机环境污染
- 验证结果：
  - `uv run pytest tests/ -q` → 216 passed，6 个第三方 `pysrt` deprecation warnings
  - `uv run ruff check src tests` → pass
  - `uv run ruff format --check src tests` → 63 files already formatted
  - `git diff --check` → pass
  - `uv run yt2notion --help` → 仅 `process/prepare/transcribe`
- 下一步：提交并推送 review 修复，合入 PR 后同步本地 `main`
