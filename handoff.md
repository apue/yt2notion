# handoff.md

本文件用于在 User、Claude Code、Opus、Codex 之间交接任务。任何 agent 接手前先读这里；任何 agent 离开前更新这里。它是当前任务的唯一活跃状态面板，不能被聊天上下文或 `docs/plan.md` 替代。

## 当前任务卡

- 任务：为 `yt2notion` 设计一个基于现有 pipeline 的简单 CLI agent（Codex 后端、Obsidian 存储、禁用 full mode、支持排队处理 / 进度查询 / 终端通知）
- 状态：`in_progress`
- 当前 owner：Codex
- 上一执行者：User
- 下一执行者：User
- 来源：用户提出新需求，已完成方案、spec、plan，并进入 subagent-driven implementation 与收口阶段
- 目标：
  - 交付 file-backed CLI agent MVP：提交任务、查看状态、查看进度、查看日志、重试、前台/后台 drain
  - 约束在 `model.backend=codex_cli`、`storage.backend=obsidian`、`output.mode=summary`
  - 约束在独立 `agent.yaml` 与独立 runtime `AGENTS.md`
  - 尽量复用现有 pipeline，避免改动核心步骤和 JSON 契约
  - 以“单用户本地自用”标准收口，不继续追求 JSON 状态文件的强一致
- 非目标：
  - 不引入 full mode
  - 不触发 Notion 发布路径
  - 不把当前 file-backed 状态层提升到数据库级事务一致性
  - 不在本轮实现 SQLite 状态后端
- 约束：
  - pipeline/contract 事实以 `PROJECT_MAP.md` 为准
  - 新 agent 应默认运行在 no-publish / summary-only 约束下，除非用户后续另行确认
  - 当前 MVP 假设单用户使用；允许“worker 运行时继续 add 新任务”，但不把多 CLI 强并发作为硬性保证目标
- 受影响文件：
  - [src/yt2notion/agent_runtime.py](./src/yt2notion/agent_runtime.py)
  - [src/yt2notion/agent_worker.py](./src/yt2notion/agent_worker.py)
  - [src/yt2notion/cli.py](./src/yt2notion/cli.py)
  - [src/yt2notion/pipeline.py](./src/yt2notion/pipeline.py)
  - [src/yt2notion/models/llm.py](./src/yt2notion/models/llm.py)
  - [src/yt2notion/models/__init__.py](./src/yt2notion/models/__init__.py)
  - [src/yt2notion/models/codex_cli.py](./src/yt2notion/models/codex_cli.py)
  - [tests/test_agent_runtime.py](./tests/test_agent_runtime.py)
  - [tests/test_agent_worker.py](./tests/test_agent_worker.py)
  - [tests/test_cli.py](./tests/test_cli.py)
  - [tests/test_pipeline.py](./tests/test_pipeline.py)
  - [tests/test_codex_cli.py](./tests/test_codex_cli.py)
  - [PROJECT_MAP.md](./PROJECT_MAP.md)
  - [handoff.md](./handoff.md)
- 验收标准：
  - `agent` 命令组可用，且 runtime control plane 与 repo 开发控制面分离
  - 现有 pipeline 可在 agent 模式下以 `codex_cli + obsidian + summary` 顺序处理队列
  - 状态、日志、retry、stale worker 基础恢复可用
  - `PROJECT_MAP.md` 与本文件同步到当前实现与已接受边界
- 建议命令：
  - `uv run pytest tests/test_agent_runtime.py tests/test_agent_worker.py tests/test_cli.py tests/test_pipeline.py tests/test_codex_cli.py -q`
  - `uv run ruff check src/yt2notion/agent_runtime.py src/yt2notion/agent_worker.py src/yt2notion/cli.py src/yt2notion/pipeline.py src/yt2notion/models/codex_cli.py src/yt2notion/models/llm.py src/yt2notion/models/__init__.py tests/test_agent_runtime.py tests/test_agent_worker.py tests/test_cli.py tests/test_pipeline.py tests/test_codex_cli.py`
- 未决问题：
  - 未来是否将 file-backed 状态层替换为 SQLite
  - 是否需要系统通知而不只是 log / worker stdout / foreground terminal 输出

## 当前执行记录

- 已完成：
  - 方案确认：命令触发、文件状态衔接、无常驻 daemon
  - 配置确认：独立 `agent.yaml`，独立 runtime `AGENTS.md`，固定 `codex_cli + obsidian + summary`
  - spec 已完成：[docs/superpowers/specs/2026-04-07-cli-agent-design.md](./docs/superpowers/specs/2026-04-07-cli-agent-design.md)
  - plan 已完成：[docs/superpowers/plans/2026-04-07-cli-agent.md](./docs/superpowers/plans/2026-04-07-cli-agent.md)
  - 已完成实现：
    - runtime config/state 层
    - Codex runtime workdir 隔离
    - pipeline progress callback
    - file-backed worker / queue / retry / stale worker 基础恢复
    - `agent` CLI 命令组
  - 已与用户确认收口标准：
    - 当前 file-backed 状态层按单用户本地自用 MVP 接受
    - 不继续为 JSON 状态文件追求数据库级一致性
    - 后续若要强化一致性，优先引入 SQLite 而不是继续补 JSON 事务语义
- 当前阻塞：
  - 无硬阻塞；正在做收口文档与最终验证，准备提 PR
- 已修改文件：
  - [src/yt2notion/agent_runtime.py](./src/yt2notion/agent_runtime.py)
  - [src/yt2notion/agent_worker.py](./src/yt2notion/agent_worker.py)
  - [src/yt2notion/cli.py](./src/yt2notion/cli.py)
  - [src/yt2notion/pipeline.py](./src/yt2notion/pipeline.py)
  - [src/yt2notion/models/llm.py](./src/yt2notion/models/llm.py)
  - [src/yt2notion/models/__init__.py](./src/yt2notion/models/__init__.py)
  - [src/yt2notion/models/codex_cli.py](./src/yt2notion/models/codex_cli.py)
  - [tests/test_agent_runtime.py](./tests/test_agent_runtime.py)
  - [tests/test_agent_worker.py](./tests/test_agent_worker.py)
  - [tests/test_cli.py](./tests/test_cli.py)
  - [tests/test_pipeline.py](./tests/test_pipeline.py)
  - [tests/test_codex_cli.py](./tests/test_codex_cli.py)
  - [PROJECT_MAP.md](./PROJECT_MAP.md)
  - [handoff.md](./handoff.md)
- 已运行验证：
  - `uv run pytest tests/test_agent_worker.py tests/test_cli.py -q` → `40 passed`
  - `uv run ruff check src/yt2notion/agent_worker.py src/yt2notion/cli.py tests/test_agent_worker.py tests/test_cli.py` → pass
- 风险/回滚点：
  - file-backed queue / worker state 是 best-effort，本轮不承诺数据库级事务一致性
  - 少量 reviewer 指出的极端多进程竞争/崩溃窗口被有意接受为 MVP residual risk，而不是继续在 JSON 文件上过度工程
- 下一步：
  - 跑一轮更完整的 focused verification
  - 提交当前实现与文档
  - 创建 PR

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
