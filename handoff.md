# handoff.md

本文件用于在 User、Claude Code、Opus、Codex 之间交接任务。任何 agent 接手前先读这里；任何 agent 离开前更新这里。它是当前任务的唯一活跃状态面板，不能被聊天上下文或 `docs/plan.md` 替代。

## 当前任务卡

- 任务：完成三项需求落地并验证：summary/full mode、Codex backend、Codex slash command；补齐单测并跑通 Apple Podcasts 到 Obsidian 的端到端
- 状态：`done`
- 当前 owner：Codex
- 上一执行者：User
- 下一执行者：User
- 来源：用户要求用 subagent 产出开发计划并完成改造，补充分测试后执行指定 Apple Podcasts 链接的端到端验证（默认 Obsidian）
- 目标：
  - 产出三项需求开发计划（里程碑 + 验收标准）
  - 完成代码改造并补齐关键单测
  - 跑通指定 URL 的端到端流程并落盘到 Obsidian
- 非目标：
  - 不发布到 Notion
  - 不做无关重构
- 约束：
  - 不回滚他人改动
  - 只在本轮负责文件中做最小改动
  - pipeline/contract 事实以 `PROJECT_MAP.md` 为准
- 受影响文件：
  - [src/yt2notion/pipeline.py](./src/yt2notion/pipeline.py)
  - [src/yt2notion/entity_extract.py](./src/yt2notion/entity_extract.py)
  - [src/yt2notion/extract.py](./src/yt2notion/extract.py)
  - [src/yt2notion/models/codex_cli.py](./src/yt2notion/models/codex_cli.py)
  - [src/yt2notion/cli.py](./src/yt2notion/cli.py)
  - [tests/test_pipeline.py](./tests/test_pipeline.py)
  - [tests/test_entity_extract.py](./tests/test_entity_extract.py)
  - [tests/test_cli.py](./tests/test_cli.py)
  - [tests/test_model_factory.py](./tests/test_model_factory.py)
  - [tests/test_codex_cli.py](./tests/test_codex_cli.py)
  - [tests/test_agent_commands.py](./tests/test_agent_commands.py)
- 验收标准：
  - 三项需求均已落地并有对应测试
  - 全量测试通过
  - 指定 URL 端到端成功写入 Obsidian
- 建议命令：
  - `uv run pytest tests/ -q`
  - `uv run yt2notion process '<url>' -c /tmp/yt2notion-e2e-gpt54mini-serial.yaml --no-confirm -v --workspace-dir <workspace>`
- 未决问题：
  - 无

## 当前执行记录

- 已完成：
  - 三项需求实现完成：`summary/full mode`、`codex_cli backend`、`.codex` slash command 入口
  - 补齐并扩展测试覆盖（pipeline/config/cli/model factory/codex backend/agent commands）
  - 优化 E2E 稳定性：网页 transcript fallback、summary 模式下 subtitle-derived 内容跳过实体抽取、实体 map-reduce 批次优化
  - 端到端成功：Apple Podcasts 指定 URL 完整跑通并写入 Obsidian
- 当前阻塞：
  - 无
- 已修改文件：
  - [src/yt2notion/pipeline.py](./src/yt2notion/pipeline.py)
  - [src/yt2notion/entity_extract.py](./src/yt2notion/entity_extract.py)
  - [src/yt2notion/extract.py](./src/yt2notion/extract.py)
  - [src/yt2notion/models/codex_cli.py](./src/yt2notion/models/codex_cli.py)
  - [src/yt2notion/cli.py](./src/yt2notion/cli.py)
  - [tests/test_pipeline.py](./tests/test_pipeline.py)
  - [tests/test_entity_extract.py](./tests/test_entity_extract.py)
  - [tests/test_cli.py](./tests/test_cli.py)
  - [tests/test_config.py](./tests/test_config.py)
  - [tests/test_model_factory.py](./tests/test_model_factory.py)
  - [tests/test_agent_commands.py](./tests/test_agent_commands.py)
  - [tests/test_codex_cli.py](./tests/test_codex_cli.py)
  - [handoff.md](./handoff.md)
- 已运行验证：
  - `uv run pytest tests/test_pipeline.py tests/test_entity_extract.py tests/test_cli.py tests/test_codex_cli.py tests/test_config.py tests/test_model_factory.py tests/test_agent_commands.py -q` -> `65 passed`
  - `uv run ruff check src/yt2notion/pipeline.py src/yt2notion/entity_extract.py tests/test_pipeline.py tests/test_entity_extract.py` -> `All checks passed`
  - `uv run pytest tests/ -q` -> `227 passed`
  - `uv run yt2notion process 'https://podcasts.apple.com/us/podcast/google-part-iii-the-ai-company/id1050462261?i=1000730326283' -c /tmp/yt2notion-e2e-gpt54mini-serial.yaml --no-confirm -v --workspace-dir /tmp/yt2notion-e2e-workspace-15` -> 成功发布到 Obsidian
- 风险/回滚点：
  - `codex exec` 真实运行时延迟仍可能波动，当前通过 summary 模式降载规避主要卡点
  - slash-command 测试是文档契约级，不覆盖宿主端 UI 集成行为
- 下一步：
  - 用户在 Obsidian 校验产物内容与格式；如需 `full` 模式 transcript 页面产物，再补跑一次 `--mode full` 验证

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
| 2026-04-03 | User | Codex | 审计三项需求测试覆盖并补测，输出开发计划 | 完成 |
