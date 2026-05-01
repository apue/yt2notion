# handoff.md

本文件用于在 User、Claude Code、Opus、Codex 之间交接任务。任何 agent 接手前先读这里；任何 agent 离开前更新这里。它是当前任务的唯一活跃状态面板，不能被聊天上下文或 `docs/plan.md` 替代。

## 当前任务卡

- 任务：bundle-only 输出收敛 + transcript cleanup 策略统一 + 删除存量死代码
- 状态：`ready_for_user_review`（实现、本地验证、PR、自我 review 已完成；等待 User 决定是否合入）
- 当前 owner：User
- 上一执行者：Codex
- 下一执行者：User
- 来源：用户明确反馈“现在就只需要这三篇输出，其它都不用”；当前正式输出只保留 `source`、`A 导读`、`B 扩展` 三篇。auto caption 也应视作 ASR-like，需要清洗；未来输出变化可重新开发，历史实验/兼容路径无保留价值。
- 实现工作目录：`/tmp/yt2notion-main-final-1777534880`
- 分支：`bundle-only-transcript-cleanup`
- 已提交 commit：`43bc800 docs: plan bundle-only transcript cleanup`、`3b9ac37 refactor: enforce bundle-only pipeline`、`c70e7be docs: sync bundle-only cleanup references`
- PR：[#25](https://github.com/apue/yt2notion/pull/25)
- review 状态：Codex 自我 review 已完成并在 PR 评论记录；GitHub 无 checks reported；本地测试/lint 通过
- 目标：
  - Pipeline 收敛为 bundle-only：只产出并发布 `source` / `A 导读` / `B 扩展`。
  - 删除 legacy single summary、full transcript 子页、entity extraction、LLM chapter extraction、map/reduce/chinese prompt 等不再运行路径。
  - transcript cleanup 策略：manual subtitle 跳过清洗；auto caption / webpage transcript / ASR / legacy subtitle 均走 cleanup。
  - 同步 `PROJECT_MAP.md`、`README.md`、`config.example.yaml` 等设计/契约文档。
- 非目标：
  - 不优化 prompt 文案。
  - 不新增输出形态。
  - 不调用远程 ASR/LLM/Notion/Obsidian 验证。
- 约束：
  - `PROJECT_MAP.md` 是 pipeline / artifact / prompt binding 唯一事实锚点。
  - 用户希望 aggressive cleanup，不要求 backward compatibility。
  - `prompts/` 下仍保留的生产模板 Markdown 结构不要改。
- 已完成：
  - 恢复并重写 `tests/test_pipeline.py`，覆盖 bundle-only、cleanup policy、Obsidian bundle publish、ASR checkpoint 保留语义。
  - `pipeline.py` 保持 bundle-only `PreparedContent`，`prepare_content()` 总是构建 `note_bundle.json`，`mode="full"` 早拒绝，非 dry-run publish 仅允许 Obsidian。
  - subtitle 下载现在记录 `manual_subtitle` / `auto_caption` 来源；webpage transcript 记录 `webpage_transcript`；resume 旧 workspace 无 marker 时按 legacy `subtitle` 清洗。
  - 删除旧 prompt 文件；backend protocol / Claude / Anthropic / Codex 测试已收敛到 `compose_*`。
  - 删除 `entity_extract.py`、`chapter_extract.py` 及对应测试；description chapter 仅走本地 timestamp regex。
  - `review.py` 删除 `review_with_context` 分支，只保留 `review.md` baseline cleanup。
  - `workspace.py` 步骤收敛为 `download -> segment -> transcribe -> review -> summarize`，移除 `entities.json` / `summary.json` helpers，新增 subtitle source marker roundtrip。
  - `config.py` 只接受 `output.mode = summary`，忽略 legacy `output.note_mode`。
  - `PROJECT_MAP.md` / `README.md` / `config.example.yaml` 已同步 bundle-only 事实。
- 已删除/改写测试：
  - 删除旧实体抽取、LLM chapter extract、旧 integration、旧 parser extended、entity obsidian 测试。
  - 保留 Obsidian/Notion legacy storage 测试与现有 storage 代码（当前 pipeline 不再调用 legacy `save()`）。
- 已运行验证：
  - `ANTHROPIC_API_KEY= UV_CACHE_DIR=/tmp/uv-cache uv run --extra dev pytest tests/ -q` → `330 passed, 6 warnings`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run --extra dev ruff check src/yt2notion tests` → `All checks passed!`（仅 `TCH003` remap warning）
- 最后一次自测：`ANTHROPIC_API_KEY= UV_CACHE_DIR=/tmp/uv-cache uv run --extra dev pytest tests/ -q`；随后 `UV_CACHE_DIR=/tmp/uv-cache uv run --extra dev ruff check src/yt2notion tests`
- 当前阻塞：无
- 下一步：User review PR #25；如确认通过，再由 User 明确批准后合入 `main`。
- 风险/回滚点：
  - 未执行任何在线 LLM/ASR/Notion/Obsidian 验证。
  - storage 层仍保留 legacy `save()` 能力以避免本轮扩大到存储后端删除；pipeline 已不调用。

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
