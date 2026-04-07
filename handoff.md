# handoff.md

本文件用于在 User、Claude Code、Opus、Codex 之间交接任务。任何 agent 接手前先读这里；任何 agent 离开前更新这里。它是当前任务的唯一活跃状态面板，不能被聊天上下文或 `docs/plan.md` 替代。

## 当前任务卡

- 任务：为 `yt2notion` 设计一个基于现有 pipeline 的简单 CLI agent（Codex 后端、Obsidian 存储、禁用 full mode、支持排队处理 / 进度查询 / 终端通知）
- 状态：`planned`
- 当前 owner：Codex
- 上一执行者：User
- 下一执行者：User
- 来源：用户提出新需求，希望先阅读项目并给出方案想法，再决定实现方向
- 目标：
  - 评估现有 `prepare/process/workspace` 是否足以支撑 agent 外壳
  - 明确最小可行 CLI 交互：提交任务、查看状态、查看进度、完成通知
  - 约束在 `model.backend=codex_cli`、`storage.backend=obsidian`、`output.mode=summary`
  - 约束在独立 `agent.yaml` 与独立 runtime `AGENTS.md`
  - 尽量复用现有 pipeline，避免改动核心步骤和 JSON 契约
- 非目标：
  - 本轮先不直接实现
  - 不引入 full mode
  - 不触发 Notion 发布路径
- 约束：
  - pipeline/contract 事实以 `PROJECT_MAP.md` 为准
  - 不回滚当前 worktree 里已有的未提交改动
  - 新 agent 应默认运行在 no-publish / summary-only 约束下，除非用户后续另行确认
- 受影响文件：
  - [src/yt2notion/cli.py](./src/yt2notion/cli.py)
  - [src/yt2notion/pipeline.py](./src/yt2notion/pipeline.py)
  - [src/yt2notion/workspace.py](./src/yt2notion/workspace.py)
  - [src/yt2notion/models/codex_cli.py](./src/yt2notion/models/codex_cli.py)
  - [src/yt2notion/storage/obsidian.py](./src/yt2notion/storage/obsidian.py)
  - [PROJECT_MAP.md](./PROJECT_MAP.md)
  - [handoff.md](./handoff.md)
- 验收标准：
  - 给出 2-3 个可实现方案及 tradeoff
  - 给出推荐 MVP 边界与后续实现切分
  - 获得用户对方向的确认，再进入设计/计划或实现
- 建议命令：
  - `uv run yt2notion prepare "URL" --mode summary`
  - `uv run yt2notion process "URL" --mode summary`
  - `rg -n "resume|workspace|codex_cli|obsidian" src/yt2notion`
- 未决问题：
  - agent 是否需要常驻后台进程，还是接受“单前台 + 轮询查询”的轻量模型
  - 终端通知是否只需 stdout / bell，还是要接入系统通知
  - 用户 share 内容的入口形态是命令行 `add URL` 还是 stdin / clipboard 集成

## 当前执行记录

- 已完成：
  - 读取 `AGENTS.md`、`handoff.md`、`CLAUDE.md`、`PROJECT_MAP.md`、`.cursorrules`
  - 阅读 `cli.py`、`pipeline.py`、`workspace.py`、`models/codex_cli.py`、`models/llm.py`、`storage/obsidian.py`、`config.py`
  - 确认现有基础能力：`codex_cli` backend、`obsidian` storage、workspace artifact 持久化、resume from step、prepare no-publish 输出
  - 确认现有缺口：没有任务队列、没有统一状态文件、没有进度查询命令、没有完成通知机制
  - 与用户确认 agent 采用“命令触发 + 本地文件状态衔接”的轻量模型，不做常驻进程
  - 与用户确认运行时控制面独立于仓库开发控制面：使用极简 `agent.yaml` 与独立 runtime `AGENTS.md`
  - 将此前遗留的 `RetryExhaustedError` 代码清理单独拆分为 PR #11 并已合入 `main`
- 当前阻塞：
  - 无
- 已修改文件：
  - [handoff.md](./handoff.md)
- 已运行验证：
  - `git status --short`
  - `git diff --stat`
  - 多个 `sed` / `rg` 只读检查命令
- 风险/回滚点：
  - 本任务尚未产出设计文档与实现计划；当前只同步了交接状态
- 下一步：
  - 为 CLI agent 撰写正式设计文档，细化命令集、状态文件、runtime 目录和执行约束

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
