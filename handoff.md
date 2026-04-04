# handoff.md

本文件用于在 User、Claude Code、Opus、Codex 之间交接任务。任何 agent 接手前先读这里；任何 agent 离开前更新这里。它是当前任务的唯一活跃状态面板，不能被聊天上下文或 `docs/plan.md` 替代。

## 当前任务卡

- 任务：修复 PR #10 code review 发现的问题并完成 PR 更新（自动发布契约、full 模式文本回填正确性、resume 校验、文档锚点同步）
- 状态：`done`
- 当前 owner：Codex
- 上一执行者：User
- 下一执行者：User
- 来源：用户要求基于 review 反馈做完整修复、保证测试通过，并用 `gh` 命令完成 PR
- 目标：
  - 明确 `process` 默认自动发布契约并消除接口歧义
  - 修复 full 模式长内容复审回填错位
  - 补齐 resume `summarize` 对 `entities.json` 的严格校验
  - 去除重复 transcript markdown 渲染实现
  - 更新 `PROJECT_MAP.md` / `README.md` 行为说明
- 非目标：
  - 不引入新功能
  - 不做超出本轮问题的架构重构
- 约束：
  - 不回滚他人改动
  - pipeline/contract 事实以 `PROJECT_MAP.md` 为准并同步文档
- 受影响文件：
  - [src/yt2notion/pipeline.py](./src/yt2notion/pipeline.py)
  - [src/yt2notion/cli.py](./src/yt2notion/cli.py)
  - [src/yt2notion/models/codex_cli.py](./src/yt2notion/models/codex_cli.py)
  - [tests/test_pipeline.py](./tests/test_pipeline.py)
  - [tests/test_cli.py](./tests/test_cli.py)
  - [tests/test_integration.py](./tests/test_integration.py)
  - [PROJECT_MAP.md](./PROJECT_MAP.md)
  - [README.md](./README.md)
  - [handoff.md](./handoff.md)
- 验收标准：
  - 关键 review 问题修复完成
  - 全量测试通过
- 建议命令：
  - `uv run pytest tests/ -q`
  - `uv run ruff check src/yt2notion/cli.py src/yt2notion/pipeline.py src/yt2notion/models/codex_cli.py tests/test_cli.py tests/test_pipeline.py tests/test_integration.py`
- 未决问题：
  - 无

## 当前执行记录

- 已完成：
  - 移除 `process`/`run_pipeline` 中 `no_confirm` 契约，`process` 明确默认自动发布
  - `--from` 帮助文案更新为 `download/segment/transcribe/review/extract/summarize`
  - `prepare` 复用 `pipeline.render_transcript_markdown()`，去除 CLI 重复实现
  - 修复 `_merge_segments_into_groups` 与 `_redistribute_reviewed_text` 分组不一致导致的错位回填
  - `resume_from="summarize"` 严格要求 `entities.json` 存在
  - 修复 `codex exec` 失败时临时文件未清理的问题
  - 删除未使用的 `_step_deferred_review`，避免行为误导
  - 同步更新 `PROJECT_MAP.md` / `README.md` 的实际 pipeline 与发布语义说明
- 当前阻塞：
  - 无
- 已修改文件：
  - [src/yt2notion/pipeline.py](./src/yt2notion/pipeline.py)
  - [src/yt2notion/cli.py](./src/yt2notion/cli.py)
  - [src/yt2notion/models/codex_cli.py](./src/yt2notion/models/codex_cli.py)
  - [tests/test_pipeline.py](./tests/test_pipeline.py)
  - [tests/test_cli.py](./tests/test_cli.py)
  - [tests/test_integration.py](./tests/test_integration.py)
  - [PROJECT_MAP.md](./PROJECT_MAP.md)
  - [README.md](./README.md)
  - [handoff.md](./handoff.md)
- 已运行验证：
  - `uv run ruff check src/yt2notion/cli.py src/yt2notion/pipeline.py src/yt2notion/models/codex_cli.py tests/test_cli.py tests/test_pipeline.py tests/test_integration.py` -> `All checks passed`
  - `uv run pytest tests/ -q` -> `234 passed`
- 风险/回滚点：
  - 仓库全量 `ruff check src tests` 仍有历史基线问题（`RetryExhausted` 命名、`tests/test_retry.py` import 排序），与本次修复无关
- 下一步：
  - 使用 `gh` 提交 commit 并推送到 PR #10 分支

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
| 2026-04-04 | User | Codex | 修复 PR #10 review 问题并同步文档/测试 | 完成 |
