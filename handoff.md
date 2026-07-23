# handoff.md

## 当前任务卡

- 任务：删除兼容层、旧产品面和重复测试，收敛到当前支持的 CLI
- 状态：`validated_locally`
- 当前 owner：Codex
- 分支：`cleanup/remove-redundant-surfaces`
- PR：待创建
- review 状态：待创建 PR 后执行双轴 review
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
  - 测试从 341 个降至 209 个，代码/测试/文档合计净减少 16,452 行
- 验证结果：
  - `env -u ANTHROPIC_API_KEY uv run --extra dev pytest tests/ -q` → 209 passed
  - `uv run --extra dev ruff check src/yt2notion tests` → pass
  - `uv run --extra dev ruff format --check src/yt2notion tests` → pass
  - `uv run yt2notion --help` → 仅 `process/prepare/transcribe`
- 下一步：提交、创建 PR、执行双轴 review、处理 findings 后复测并合入
