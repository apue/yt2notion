# handoff.md

本文件用于在 User、Claude Code、Opus、Codex 之间交接任务。任何 agent 接手前先读这里；任何 agent 离开前更新这里。它是当前任务的唯一活跃状态面板，不能被聊天上下文或 `docs/plan.md` 替代。

## 当前任务卡

- 任务：按 `docs/superpowers/specs/2026-04-01-pipeline-resilience-design.md` 落地 pipeline resilience，采用 subagent 并行实现
- 状态：`done`
- 当前 owner：Codex
- 上一执行者：User
- 下一执行者：User
- 来源：用户要求对照 resilience design 检查实现状态，并在未完成时按 design 落地
- 目标：
  - 补齐 retry / failure tracking / unattended execution 的设计闭环
  - 让 pipeline 在无人值守场景下更稳健
  - 保持现有插件架构、数据契约与发布语义不被无关改动破坏
- 非目标：
  - 不改 prompt 模板结构
  - 不做与 resilience 无关的重构
  - 不引入新的外部服务或配置项
- 约束：
  - 以 design 文档为准，对照代码逐项落地
  - 并行工作必须按文件边界切分，避免 worker 冲突
  - 继续遵守仓库“不自动发布到 Notion”的总体底线；本次只移除 pipeline 内交互确认以支持 unattended execution
- 受影响文件：
  - [src/yt2notion/pipeline.py](./src/yt2notion/pipeline.py)
  - [src/yt2notion/workspace.py](./src/yt2notion/workspace.py)
  - [src/yt2notion/transcribe/remote.py](./src/yt2notion/transcribe/remote.py)
  - [src/yt2notion/models/claude_code.py](./src/yt2notion/models/claude_code.py)
  - [src/yt2notion/cli.py](./src/yt2notion/cli.py)
  - [tests/test_pipeline.py](./tests/test_pipeline.py)
  - [tests/test_workspace.py](./tests/test_workspace.py)
  - [tests/test_claude_code.py](./tests/test_claude_code.py)
  - [tests/test_transcribe.py](./tests/test_transcribe.py)
  - [tests/test_transcriber_retry.py](./tests/test_transcriber_retry.py)
  - [handoff.md](./handoff.md)
- 验收标准：
  - `RemoteTranscriber`、`ClaudeCodeCaller`、`ClaudeCodeModel` 的 retry 行为符合 design
  - pipeline 去除交互 confirm，失败时写 `failed.json`，成功时清理
  - deferred review 仅在 retries exhausted 时显式降级，并保留 transcript 交付
  - 测试覆盖关键 resilience 行为
- 建议命令：
  - `uv run pytest tests/test_retry.py tests/test_llm_retry.py tests/test_claude_code.py tests/test_transcribe.py tests/test_pipeline.py tests/test_workspace.py -v`
  - `uv run pytest tests/test_transcriber_retry.py -v`
  - `uv run ruff check src/ tests/`
- 未决问题：
  - 是否需要保留 `--no-confirm` CLI 参数作为纯兼容占位

## 当前执行记录

- 已完成：
  - 对照 design 与代码确认：`retry.py` 与 `ClaudeCodeCaller.call()` 已完成
  - 确认仍未完成：`RemoteTranscriber` retry、`ClaudeCodeModel` retry、pipeline 顶层 failure tracking、workspace failure artifact、deferred review 显式降级、移除交互 confirm
  - 规划 subagent 切分：`pipeline/workspace`、`ASR retry`、`Claude summarizer retry`
  - `ClaudeCodeModel._call_claude()` 已接入共享 retry helper、`timeout=120` 和空输出重试
  - `tests/test_claude_code.py` 已补齐 retries / timeout / missing CLI 的定向测试
  - `RemoteTranscriber.transcribe()` 已接入共享 retry helper，对连接错误、超时、HTTP 5xx 重试；HTTP 4xx 与 JSON decode 立即失败
  - `run_pipeline()` 默认无人值守运行，不再触发交互 confirm；保留 `no_confirm` 参数仅作兼容
  - `Workspace` 新增 `save_failure()` / `load_failure()` / `clear_failure()`，pipeline 失败时写 `failed.json`，成功发布后清理
  - deferred review 改为仅在 `RetryExhausted` 时显式降级，并在 transcript 顶部注入警告说明
  - 修正 `tests/test_integration.py`，去掉对固定 `claude -p` 调用次数的脆弱假设，并隔离 entity extraction 的 haiku 调用
- 当前阻塞：
  - 无
- 已修改文件：
  - [src/yt2notion/models/claude_code.py](./src/yt2notion/models/claude_code.py)
  - [src/yt2notion/pipeline.py](./src/yt2notion/pipeline.py)
  - [src/yt2notion/transcribe/remote.py](./src/yt2notion/transcribe/remote.py)
  - [src/yt2notion/workspace.py](./src/yt2notion/workspace.py)
  - [tests/test_claude_code.py](./tests/test_claude_code.py)
  - [tests/test_integration.py](./tests/test_integration.py)
  - [tests/test_pipeline.py](./tests/test_pipeline.py)
  - [tests/test_transcriber_retry.py](./tests/test_transcriber_retry.py)
  - [tests/test_workspace.py](./tests/test_workspace.py)
  - [handoff.md](./handoff.md)
- 已运行验证：
  - `sed -n '1,260p' docs/superpowers/specs/2026-04-01-pipeline-resilience-design.md`
  - 逐文件检查 `pipeline.py`、`workspace.py`、`remote.py`、`llm.py`、`claude_code.py` 及对应测试
  - `uv run pytest tests/test_claude_code.py -v`
  - `uv run ruff check src/yt2notion/models/claude_code.py tests/test_claude_code.py`
  - `uv run pytest tests/test_transcriber_retry.py tests/test_transcribe.py -v`
  - `uv run pytest tests/test_pipeline.py tests/test_workspace.py -v`
  - `uv run pytest tests/test_integration.py -v`
  - `uv run pytest tests/test_retry.py tests/test_llm_retry.py tests/test_claude_code.py tests/test_transcribe.py tests/test_transcriber_retry.py tests/test_pipeline.py tests/test_workspace.py tests/test_cli.py tests/test_integration.py -q` → `58 passed`
  - `uv run ruff check src/yt2notion/pipeline.py src/yt2notion/workspace.py src/yt2notion/transcribe/remote.py src/yt2notion/models/claude_code.py tests/test_pipeline.py tests/test_workspace.py tests/test_transcriber_retry.py tests/test_claude_code.py tests/test_integration.py tests/test_cli.py` → passed
- 风险/回滚点：
  - `pipeline.py` 是关键路径中心文件，必须由单一 worker 负责以避免冲突
  - 改动 `--no-confirm` 可能影响现有 CLI 测试，需要同步修正测试预期
  - deferred review 的降级文案会影响 transcript 输出，需要保证仅在目标异常下触发
- 下一步：
  - 如需继续增强 resilience，可评估是否为 `tests/test_transcribe.py` 的连接错误用例注入无睡眠 patch，以缩短总测试耗时
  - 如需扩大覆盖面，可继续评估 `failed.json` 在 resume 场景下的用户可见提示

## 接手检查清单

- 先读 [AGENTS.md](./AGENTS.md)
- 再读本文件
- 查看当前 `git status` 与 `git diff`
- 再按需读 [CLAUDE.md](./CLAUDE.md)、[PROJECT_MAP.md](./PROJECT_MAP.md)、[.cursorrules](./.cursorrules)
- 如果当前任务与本文件不一致，先更新本文件再继续

## 交接模板

复制下面模板，为新任务填写最新状态。

### 任务卡

- 任务：
- 状态：`planned` / `in_progress` / `blocked` / `done`
- 当前 owner：
- 上一执行者：
- 下一执行者：
- 来源：
- 目标：
- 非目标：
- 约束：
- 受影响文件：
- 验收标准：
- 建议命令：
- 未决问题：

### 执行记录

- 已完成：
- 当前阻塞：
- 已修改文件：
- 已运行验证：
- 风险/回滚点：
- 下一步：

## 历史

| 日期 | From | To | 任务 | 结果 |
|------|------|----|------|------|
| 2026-04-03 | User | Codex | 生成 `AGENTS.md` / `handoff.md` / `config.toml` 初稿 | 完成 |
| 2026-04-03 | User | Codex | 把工作流接入 Claude 入口并修正交接机制 | 完成 |
