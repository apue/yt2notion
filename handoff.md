# handoff.md

本文件用于在 User、Claude Code、Opus、Codex 之间交接任务。任何 agent 接手前先读这里；任何 agent 离开前更新这里。它是当前任务的唯一活跃状态面板，不能被聊天上下文或 `docs/plan.md` 替代。

## 当前任务卡

- 任务：以高内聚、低耦合的用例 Interface + provider Adapter 重构 pipeline 架构
- 状态：`pr_ready`
- 当前 owner：Codex
- 上一执行者：GPT-5.5 medium implementation subagent / Codex review owner
- 下一执行者：Codex GitHub workflow / User merge decision
- 来源：User 要求从最佳实践重新审视长 pipeline；确认采用统一能力接口、行为各异的 provider Adapter，并要求由 GPT-5.5 medium 子代理实施。User 授权实现细节自主设计，原则为高内聚、低耦合。
- 当前工作目录：`/Users/yangtian/Developer/agent/yt2notion`
- 分支：`architecture-usecase-interfaces`
- PR：待创建
- review 状态：双轴 review 最终 Standards / Spec 均无 findings；正式 `/review` 的三轮 findings 均已修复并本地复测
- 目标：
  - 提供显式 `Yt2Notion.prepare/process/transcribe` 应用 Interface。
  - 提供高层 `MediaSource` Protocol 和 config 选择的 yt-dlp primary Adapter。
  - 将音频规划、分片、checkpoint、Groq 等待/降级和真实 backend 结果内聚到 `TranscriptionEngine`。
  - 主 pipeline 与 transcript-only 路径复用同一引擎，不再跨模块调用 pipeline 私有函数。
  - 保持 CLI、artifact、resume/fresh 和发布安全行为兼容。
- 非目标：
  - 不引入通用 Node/DAG/registry/plugin discovery。
  - 不实现 ElevenLabs 等新 provider。
  - 不修改 prompt 结构、凭证或自动发布策略。
  - 不在无 benchmark 的情况下改变 ASR 性能参数。
- 约束：
  - `PROJECT_MAP.md` 是 pipeline / artifact / extension 事实锚点，结构事实变化先更新该文件。
  - 现有用户本地改动 `.codex/config.toml`、`.gitignore` 保留，不作为本功能必要改动处理。
  - 实现及 review 后只做本地测试/lint，不调用远程 ASR/LLM/Storage。
- 受影响文件：
  - [docs/harness/](./docs/harness/)
  - [PROJECT_MAP.md](./PROJECT_MAP.md)
  - [src/yt2notion/application.py](./src/yt2notion/application.py)
  - [src/yt2notion/media_source/](./src/yt2notion/media_source/)
  - [src/yt2notion/transcribe/](./src/yt2notion/transcribe/)
  - [src/yt2notion/pipeline.py](./src/yt2notion/pipeline.py)
  - [src/yt2notion/media_transcribe.py](./src/yt2notion/media_transcribe.py)
  - [src/yt2notion/cli.py](./src/yt2notion/cli.py)
  - [src/yt2notion/agent_worker.py](./src/yt2notion/agent_worker.py)
  - 相关 tests
- 验收标准：
  - 详见 [docs/harness/ACCEPTANCE.md](./docs/harness/ACCEPTANCE.md)。
- 已完成：
  - 已完成三套独立架构设计比较，均拒绝通用 DAG/Node，收敛到显式 use-case + 深 Module。
  - 已完成并接受 SPEC、ARCHITECTURE、ACCEPTANCE、DECISIONS、VALIDATION_PLAN、复用/清理报告。
  - 已创建分支 `architecture-usecase-interfaces`。
  - 已新增 `Yt2Notion.prepare/process/transcribe` 应用 Interface 与 `create_yt2notion()` composition root。
  - 已新增高层 `MediaSource` Protocol、typed acquire request/result、config 选择的 `yt_dlp` Adapter 与工厂。
  - 已将 provider 配置注入 Adapter 构造器，并用 content/transcript 两种 result 类型避免 optional 字段袋。
  - 已将 ASR chunking / checkpoint / hourly wait / daily fallback / backend outcome 迁入 `transcribe.engine.TranscriptionEngine`。
  - 已新增 `ContentPreparation` 深模块，application 不再反向导入 pipeline；pipeline 仅保留兼容 facade/wrapper。
  - 已通过 `create_transcription_engine()` 延迟注入 primary/fallback `Transcriber` Adapter，避免未用 ASR 时提前读取凭证。
  - 已让 CLI process/prepare、agent worker、standalone transcribe 路径经由应用 Interface；`media_transcribe.py` 不再导入 pipeline 私有函数。
  - 已保留 `pipeline.py` 兼容 facade/helper patch points，并更新 `PROJECT_MAP.md`、`config.example.yaml` 与 tests。
  - 已补齐下载/转写失败记录、成功后清理失败标记、provider video path、旧 transcript renderer 兼容和 fallback Adapter 单例生命周期。
- 已运行验证：
  - 架构前基线：`329 passed, 6 warnings`；ruff check passed。
  - review 修复后 focused tests → `49 passed, 1 warning`
  - 最终 `env -u ANTHROPIC_API_KEY uv run --extra dev pytest tests/ -q` → `341 passed, 6 warnings`
  - `uv run --extra dev ruff check src/yt2notion tests` → `All checks passed!`
  - changed-source `uv run --extra dev ruff format --check ...` → pass
  - `rg` architecture checks: no `media_transcribe.py` private pipeline import; ASR state machine owner is `transcribe/engine.py`; no new DAG/Node/registry implementation found.
- 当前阻塞：
  - 无；待 commit / push / PR。
- 下一步：
  1. 仅暂存本任务文件，排除用户本地 `.codex/config.toml`、`.gitignore`。
  2. 创建/更新 PR，交由 User 决定最终 merge。
- 风险/回滚点：
  - ASR 状态机迁移已由本地 regression tests 覆盖，但未做任何远程 Groq / remote ASR 在线验证。
  - `pipeline.py` 仍保留 behavior-free compatibility helper patch points；正式移除需后续明确批准。

## 上一任务归档（2026-04-30 前）

- 任务：实现 Groq 音频转写 checkpoint / ASH 等待恢复 / ASD 剩余 chunk remote fallback
- 状态：`done`
- 当前 owner：User
- 上一执行者：Codex
- 下一执行者：User
- 来源：用户要求一气呵成完成 spec、plan、subagent-driven development、GitHub PR workflow
- 分支：`groq-transcribe-checkpoint`
- PR：[#21](https://github.com/apue/yt2notion/pull/21)（已于 2026-04-19 合入 `main`，merge commit `d8cfe862`）
- review 状态：本地 subagent / final reviewer 复核完成并已合入；未配置 GitHub checks，本次以本地最小充分测试和 lint 作为合入依据
- 目标：
  - 新增 chunk 级转写 checkpoint，尊重已完成 chunk 结果
  - Groq `ASH` 读取 `retry-after` 并在当前进程内等待恢复
  - Groq `ASD` 时，从当前失败 chunk 开始将当前 job 剩余 chunk 全部切到 `remote`
  - 将 checkpoint 契约沉淀到 `workspace/pipeline`，并更新 `PROJECT_MAP.md` / `README.md`
- 非目标：
  - 不接入 ElevenLabs
  - 不改 queue 模型或新增 scheduler
  - 不做任何连接 Groq / remote / LLM 的在线测试
- 约束：
  - 仅保留必要单元测试
  - `PROJECT_MAP.md` 作为 pipeline / artifact 唯一事实锚点
  - 当前 sandbox 不允许修改 `.git` refs，GitHub 交付可能需要 connector 兜底
- 受影响文件：
  - [PROJECT_MAP.md](./PROJECT_MAP.md)
  - [README.md](./README.md)
  - [config.example.yaml](./config.example.yaml)
  - [handoff.md](./handoff.md)
  - [docs/superpowers/specs/2026-04-19-groq-transcribe-checkpoint-design.md](./docs/superpowers/specs/2026-04-19-groq-transcribe-checkpoint-design.md)
  - [docs/superpowers/plans/2026-04-19-groq-transcribe-checkpoint.md](./docs/superpowers/plans/2026-04-19-groq-transcribe-checkpoint.md)
  - [src/yt2notion/transcribe/errors.py](./src/yt2notion/transcribe/errors.py)
  - [src/yt2notion/transcribe/groq.py](./src/yt2notion/transcribe/groq.py)
  - [src/yt2notion/workspace.py](./src/yt2notion/workspace.py)
  - [src/yt2notion/pipeline.py](./src/yt2notion/pipeline.py)
  - [tests/test_transcribe_groq.py](./tests/test_transcribe_groq.py)
  - [tests/test_workspace.py](./tests/test_workspace.py)
  - [tests/test_pipeline.py](./tests/test_pipeline.py)
- 验收标准：
  - 长音频在 `ASH` 时保留已完成 chunk，等待后从断点继续
  - `ASD` 只切当前 job 剩余 pending chunk 到 `remote`
  - `transcripts.json` 只在全部 chunk 完成后生成
  - 单元测试覆盖 Groq quota 分类、workspace checkpoint、pipeline 恢复语义
- 建议命令：
  - `uv run pytest tests/test_transcribe_groq.py tests/test_workspace.py tests/test_pipeline.py -q`
  - `uv run ruff check src/yt2notion tests`
- 未决问题：
  - Groq `429` 无法细分时，第一版保守视为 `ASH`

## 上一任务执行记录（2026-04-30 前）

- 已完成：
  - 完成讨论并确认行为边界：Groq 优先、`ASH` 等待、`ASD` 切剩余 pending chunk 到 `remote`
  - 落盘执行 spec：[docs/superpowers/specs/2026-04-19-groq-transcribe-checkpoint-design.md](./docs/superpowers/specs/2026-04-19-groq-transcribe-checkpoint-design.md)
  - 落盘实现计划：[docs/superpowers/plans/2026-04-19-groq-transcribe-checkpoint.md](./docs/superpowers/plans/2026-04-19-groq-transcribe-checkpoint.md)
  - 完成 `Groq` quota 分类、workspace checkpoint、pipeline 恢复状态机、文档与配置说明
  - 根据最终 reviewer findings 补齐 fresh rerun checkpoint 失效、`resume_from=\"transcribe\"` fallback marker 保留、missing chunk payload 自动重跑
  - 为 transcribe 增加 chunk 级诊断事件：`chunk_started` / `chunk_completed` / `hourly_wait` / `daily_fallback_switch`
  - 扩展长音频 ASR 诊断说明：`docs/agent-error-guide.md` 现在要求在 transcribe 故障时读取 `transcribe_state.json`
  - 通过远端 GitHub branch/PR 流程创建 [#21](https://github.com/apue/yt2notion/pull/21)
  - 通过 `gh pr merge 21 --squash` 将 [#21](https://github.com/apue/yt2notion/pull/21) 合入 `main`
- 当前阻塞：
  - 无
- 已修改文件：
  - [PROJECT_MAP.md](./PROJECT_MAP.md)
  - [README.md](./README.md)
  - [config.example.yaml](./config.example.yaml)
  - [docs/agent-error-guide.md](./docs/agent-error-guide.md)
  - [handoff.md](./handoff.md)
  - [docs/superpowers/specs/2026-04-19-groq-transcribe-checkpoint-design.md](./docs/superpowers/specs/2026-04-19-groq-transcribe-checkpoint-design.md)
  - [docs/superpowers/plans/2026-04-19-groq-transcribe-checkpoint.md](./docs/superpowers/plans/2026-04-19-groq-transcribe-checkpoint.md)
  - [src/yt2notion/transcribe/errors.py](./src/yt2notion/transcribe/errors.py)
  - [src/yt2notion/transcribe/groq.py](./src/yt2notion/transcribe/groq.py)
  - [src/yt2notion/workspace.py](./src/yt2notion/workspace.py)
  - [src/yt2notion/pipeline.py](./src/yt2notion/pipeline.py)
  - [tests/test_transcribe_groq.py](./tests/test_transcribe_groq.py)
  - [tests/test_workspace.py](./tests/test_workspace.py)
  - [tests/test_pipeline.py](./tests/test_pipeline.py)
- 已运行验证：
  - `uv run pytest tests/test_transcribe_groq.py tests/test_workspace.py tests/test_pipeline.py -q` → `84 passed, 4 warnings`
  - `uv run ruff check src/yt2notion/transcribe/errors.py src/yt2notion/transcribe/groq.py src/yt2notion/workspace.py src/yt2notion/pipeline.py tests/test_transcribe_groq.py tests/test_workspace.py tests/test_pipeline.py` → `All checks passed!`
  - `uv run pytest tests/test_pipeline.py tests/test_agent_worker.py -q` → `65 passed, 4 warnings`
  - `uv run ruff check src/yt2notion/pipeline.py tests/test_pipeline.py tests/test_agent_worker.py docs/agent-error-guide.md` → `All checks passed!`
  - `uv run pytest tests/test_transcribe_groq.py tests/test_workspace.py tests/test_pipeline.py tests/test_agent_worker.py -q` → `105 passed, 4 warnings`
  - `uv run ruff check src/yt2notion/transcribe/errors.py src/yt2notion/transcribe/groq.py src/yt2notion/workspace.py src/yt2notion/pipeline.py tests/test_transcribe_groq.py tests/test_workspace.py tests/test_pipeline.py tests/test_agent_worker.py docs/agent-error-guide.md` → `All checks passed!`
- 最后一次自测：
  - `uv run pytest tests/test_transcribe_groq.py tests/test_workspace.py tests/test_pipeline.py tests/test_agent_worker.py -q`
- 风险/回滚点：
  - 未做任何连接 Groq / remote / LLM 的在线验证；当前结论基于本地单元测试和静态检查
  - 当前工作树仍有用户自己的无关脏改：`AGENTS.md`、`.agents/skills/*`、`.codex/config.toml`、旧 plan 文档；PR 未包含这些文件
- 下一步：
  - 无；本轮已完成并合入

## 上一任务归档

- 任务：将 source / A / B + tags 的实验流程正式产品化为 `note_bundle` pipeline，并接入 Obsidian 三文件发布
- 状态：`done`
- 当前 owner：User
- 上一执行者：Codex
- 下一执行者：User / Codex
- 来源：用户确认 Ferrari 样本的 source/A/B 阅读体验可用，希望把这套模式固化为正式流水线：统一产出 `source + A导读 + B扩展 + tags`，并直接发布到 Obsidian
- 目标：
  - 新增 `output.note_mode = source_ab_bundle`
  - 在 summarize 阶段产出 `note_bundle.json`
  - 正式引入 `compose_guide / compose_longform / compose_note_metadata` 三个生产 prompt
  - 让 `prepare` / dry-run / `process` 都能理解 `note_bundle`
  - 在 Obsidian backend 下正式发布 `source / 导读 / 扩展` 三篇互链笔记
- 非目标：
  - 不扩展到 Notion bundle publish
  - 不在这轮接 bundle transcript 子页
  - 不清理实验脚本或旧实验 prompt
- 约束：
  - `PROJECT_MAP.md` 是唯一事实锚点，涉及 pipeline / artifact / prompt binding 变化必须先更新
  - bundle mode 当前只支持 `output.mode = summary`
  - bundle publish 当前只支持 `storage.backend = obsidian`
  - 不回退工作树里已有实验改动
- 受影响文件：
  - [PROJECT_MAP.md](./PROJECT_MAP.md)
  - [handoff.md](./handoff.md)
  - [src/yt2notion/config.py](./src/yt2notion/config.py)
  - [src/yt2notion/models/base.py](./src/yt2notion/models/base.py)
  - [src/yt2notion/models/_parsers.py](./src/yt2notion/models/_parsers.py)
  - [src/yt2notion/models/claude_code.py](./src/yt2notion/models/claude_code.py)
  - [src/yt2notion/models/anthropic_api.py](./src/yt2notion/models/anthropic_api.py)
  - [src/yt2notion/models/codex_cli.py](./src/yt2notion/models/codex_cli.py)
  - [src/yt2notion/note_bundle.py](./src/yt2notion/note_bundle.py)
  - [src/yt2notion/pipeline.py](./src/yt2notion/pipeline.py)
  - [src/yt2notion/cli.py](./src/yt2notion/cli.py)
  - [src/yt2notion/storage/base.py](./src/yt2notion/storage/base.py)
  - [src/yt2notion/storage/obsidian.py](./src/yt2notion/storage/obsidian.py)
  - [src/yt2notion/prompts/compose_guide.md](./src/yt2notion/prompts/compose_guide.md)
  - [src/yt2notion/prompts/compose_longform.md](./src/yt2notion/prompts/compose_longform.md)
  - [src/yt2notion/prompts/compose_note_metadata.md](./src/yt2notion/prompts/compose_note_metadata.md)
  - [tests/test_config.py](./tests/test_config.py)
  - [tests/test_workspace.py](./tests/test_workspace.py)
  - [tests/test_prompts.py](./tests/test_prompts.py)
  - [tests/test_note_bundle.py](./tests/test_note_bundle.py)
  - [tests/test_pipeline.py](./tests/test_pipeline.py)
  - [tests/test_obsidian_storage.py](./tests/test_obsidian_storage.py)
- 验收标准：
  - `config.output.note_mode` 在 Obsidian 下默认 `source_ab_bundle`；其它 backend 默认 `single`，仍可显式覆盖
  - workspace summarize artifact 支持 `note_bundle.json`
  - `prepare` 在 bundle mode 下返回 `note_bundle` payload
  - `process` 在 `storage.backend = obsidian` + bundle mode 下正式发布 source/A/B 三篇
  - `PROJECT_MAP.md` 已同步新的 pipeline / artifact / config / prompt 事实
- 建议命令：
  - `uv run pytest tests/test_config.py tests/test_workspace.py -q`
  - `uv run pytest tests/test_prompts.py tests/test_note_bundle.py -q`
  - `uv run pytest tests/test_obsidian_storage.py tests/test_pipeline.py -q`
  - `uv run ruff check src/yt2notion tests`
- 未决问题：
  - 是否后续支持 bundle mode 的 transcript 子页
  - 是否保留 `single` 作为长期兼容模式，还是未来继续收敛 bundle-only

## 上一任务执行记录

- 已完成：
  - Task 1：`note_mode` config、`NoteDocument/NoteBundle` typed artifact、workspace `note_bundle.json` 保存/加载完成
  - Task 2：三套生产 prompt、严格 JSON parser、三种 Summarizer backend 的 `compose_*` 接口完成
  - Task 3：`note_bundle.py` 编排、pipeline summarize 分支、CLI `prepare` payload、dry-run 渲染完成
  - Task 4：Obsidian `save_note_bundle()`、source/A/B 三文件互链发布、bundle publish backend guard 完成
  - 所有关键 review findings 已收口：
    - bundle short ASR 不再绕过 review
    - `full + source_ab_bundle` 早拒绝
    - bundle 文件名锚定 `metadata.title`，frontmatter/title 仍保留 note 自身标题
- 当前阻塞：
  - 无
- 已修改文件：
  - 见上面的“受影响文件”；当前工作树还包含更早的实验文件和文档脏改动，未回退
- 已运行验证：
  - `uv run pytest tests/test_config.py tests/test_workspace.py -q` → `37 passed`
  - `uv run pytest tests/test_prompts.py tests/test_note_bundle.py -q` → `26 passed`
  - `uv run pytest tests/test_note_bundle.py tests/test_pipeline.py -q` → `51 passed`
  - `uv run pytest tests/test_obsidian_storage.py tests/test_pipeline.py -q` → `65 passed`
  - `uv run pytest tests/test_prompts.py tests/test_note_bundle.py tests/test_pipeline.py tests/test_obsidian_storage.py -q` → `97 passed`
  - `uv run ruff check src/yt2notion/models/_parsers.py src/yt2notion/prompts/compose_guide.md src/yt2notion/prompts/compose_longform.md tests/test_prompts.py tests/test_note_bundle.py tests/test_pipeline.py tests/test_obsidian_storage.py` → pass
  - Real sample verification: `prepare_content(..., resume_from='extract', workspace_dir='~/.yt2notion-agent/workspace/1000761027849', mode='summary')` with `config.output['note_mode'] = 'source_ab_bundle'` completed and wrote `note_bundle.json`
- 风险/回滚点：
  - bundle mode 目前只支持 `output.mode = summary`
  - bundle transcript 子页还未接，source 侧当前只保证原始 source URL 和 A/B 跳转
  - note prompts now avoid long-body-in-JSON by using `<note_json>` + `<note_markdown>` tagged output; metadata prompt remains strict JSON
  - 真实大样本下的文风质量仍需用户用真实内容继续验证；当前代码层风险已通过 review 收口
- 下一步：
  - 用户体验新流程，决定是否让 runtime 默认走 `source_ab_bundle`
  - 如需继续扩展，可补 bundle transcript 子页或 Notion 侧 bundle publish

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
- 分支：
- PR：
- review 状态：
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
- 最后一次自测：
- 风险/回滚点：
- 下一步：

## 历史

| 日期 | From | To | 任务 | 结果 |
|------|------|----|------|------|
| 2026-04-17 | User | Codex | 检查最近一次 agent 错误 | 完成 |
| 2026-04-17 | User | Codex | 更新 `AGENTS.md` / `handoff.md` 以匹配 Codex 主导 workflow | 完成 |
| 2026-04-03 | User | Codex | 生成 `AGENTS.md` / `handoff.md` / `config.toml` 初稿 | 完成 |
| 2026-04-03 | User | Codex | 把工作流接入 Claude 入口并修正交接机制 | 完成 |
| 2026-04-03 | User | Codex | 审计三项需求测试覆盖并补测，输出开发计划 | 完成 |
| 2026-04-04 | User | Codex | 修复 PR #10 review 问题并同步文档/测试 | 完成 |
| 2026-04-10 | User | Codex | 新增长内容总结 prompt 变体并在真实 workspace 生成对比产物 | 完成 |
