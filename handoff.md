# handoff.md

本文件用于在 User、Claude Code、Opus、Codex 之间交接任务。任何 agent 接手前先读这里；任何 agent 离开前更新这里。它是当前任务的唯一活跃状态面板，不能被聊天上下文或 `docs/plan.md` 替代。

## 当前任务卡

- 任务：更新 `AGENTS.md` / `handoff.md`，切换到 Codex 主导协作模式并写入 PR workflow
- 状态：`done`
- 当前 owner：User
- 上一执行者：Codex
- 下一执行者：User
- 来源：用户要求按当前现实调整协作文档；先不修改 `CLAUDE.md`，只改 `AGENTS.md` 和 `handoff.md`
- 分支：`codex/update-agent-workflow-docs`
- PR：[#20](https://github.com/apue/yt2notion/pull/20)
- review 状态：纯文本改动，无需 `/review`；PR 已 ready for review
- 目标：
  - 在 `AGENTS.md` 中明确 Codex 为默认主执行者
  - 写清纯文本改动与代码改动两套 GitHub workflow
  - 在 `handoff.md` 中补充分支、PR、review、自测跟踪字段
- 非目标：
  - 不修改 `CLAUDE.md`
  - 不修改 `PROJECT_MAP.md`
  - 不改任何业务代码或 pipeline 行为
- 约束：
  - 只做文档改动
  - workflow 以 `gh` CLI 和 `/review` 为默认路径
  - 不能把 pipeline 事实错误地下沉到协作文档
- 受影响文件：
  - [AGENTS.md](./AGENTS.md)
  - [handoff.md](./handoff.md)
- 验收标准：
  - `AGENTS.md` 已反映 Codex 主导、按需规划、两套 PR workflow
  - `handoff.md` 模板已可追踪分支、PR、review 状态和最后一次自测
  - `CLAUDE.md` 保持未改动
- 建议命令：
  - `git diff -- AGENTS.md handoff.md`
- 未决问题：
  - 无

## 当前执行记录

- 已完成：
  - 重写 [AGENTS.md](./AGENTS.md) 中的默认角色分工，使 Codex 成为默认主执行者
  - 在 [AGENTS.md](./AGENTS.md) 中新增纯文本改动 / 代码改动两套 GitHub 交付 workflow
  - 调整 [handoff.md](./handoff.md) 任务卡与模板字段，补充分支、PR、review 状态和最后一次自测
  - 通过 `gh api` 在远端创建分支 `codex/update-agent-workflow-docs`，并提交文档改动
  - 创建并更新 PR [#20](https://github.com/apue/yt2notion/pull/20) 指向 `main`
- 当前阻塞：
  - 无
- 已修改文件：
  - [AGENTS.md](./AGENTS.md)
  - [handoff.md](./handoff.md)
- 已运行验证：
  - 人工检查文档改动，确认只涉及 `AGENTS.md` 与 `handoff.md`
  - 未运行测试；本次为纯文档改动
- 最后一次自测：
  - 文档 diff 自查：`git diff -- AGENTS.md handoff.md`
- 风险/回滚点：
  - [CLAUDE.md](./CLAUDE.md) 仍保留旧的“先讨论，再动手”表述；当前以 `AGENTS.md` 为更高优先级规则
- 下一步：
  - 等待用户决定是否直接合入 `main`

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
