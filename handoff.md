# handoff.md

本文件用于在 User、Claude Code、Opus、Codex 之间交接任务。任何 agent 接手前先读这里；任何 agent 离开前更新这里。它是当前任务的唯一活跃状态面板，不能被聊天上下文或 `docs/plan.md` 替代。

## 当前任务卡

- 任务：把仓库级工作流接入 Claude/Codex 实际入口
- 状态：`done`
- 当前 owner：User
- 上一执行者：Codex
- 下一执行者：待定
- 来源：用户要求基于 `CLAUDE.md`、`PROJECT_MAP.md`、`.cursorrules` 建立可执行的 agent 工作流
- 目标：
  - 让 `AGENTS.md` 成为协作总入口
  - 让 Claude 在开始规划或执行命令前显式读取 `AGENTS.md` / `handoff.md`
  - 让 `handoff.md` 成为稳定的任务切换面板
  - 为 Codex 提供仓库级基础配置
- 非目标：
  - 不修改业务代码
  - 不修改 `prompts/` 模板
  - 不改变 `youtube2notion` 的发布语义
- 约束：
  - 保持 [CLAUDE.md](./CLAUDE.md) 的“先讨论，再动手”
  - 保持“不自动发布到 Notion”的项目底线
  - 统一使用 7-step pipeline 作为正式表述
- 受影响文件：
  - [AGENTS.md](./AGENTS.md)
  - [handoff.md](./handoff.md)
  - [config.toml](./config.toml)
  - [CLAUDE.md](./CLAUDE.md)
  - [.claude/commands/plan.md](./.claude/commands/plan.md)
  - [.claude/commands/youtube2notion.md](./.claude/commands/youtube2notion.md)
- 验收标准：
  - Claude 与 Codex 的入口文件都提到 `AGENTS.md` 和 `handoff.md`
  - `handoff.md` 能独立承载任务状态、交接、下一步
  - 不引入新的发布行为变更
- 建议命令：
  - `git diff`
  - `git status --short`
- 未决问题：
  - 仓库内 `config.toml` 是否需要同步到全局 `~/.codex/config.toml`

## 当前执行记录

- 已完成：
  - 新建并修正 [AGENTS.md](./AGENTS.md)，加入启动检查、交接要求、文档优先级
  - 修正 [CLAUDE.md](./CLAUDE.md)，要求 Claude 先读 `AGENTS.md` / `handoff.md`
  - 修正 [.claude/commands/plan.md](./.claude/commands/plan.md)，要求规划结果同步到 `handoff.md`
  - 修正 [.claude/commands/youtube2notion.md](./.claude/commands/youtube2notion.md)，只接入启动检查
  - 收敛 [config.toml](./config.toml) 为最小可确认配置
- 当前阻塞：
  - 无
- 已修改文件：
  - [AGENTS.md](./AGENTS.md)
  - [handoff.md](./handoff.md)
  - [config.toml](./config.toml)
  - [CLAUDE.md](./CLAUDE.md)
  - [.claude/commands/plan.md](./.claude/commands/plan.md)
  - [.claude/commands/youtube2notion.md](./.claude/commands/youtube2notion.md)
- 已运行验证：
  - 人工核对文档一致性
  - 未运行测试；本次只修改文档与命令说明
- 风险/回滚点：
  - Claude 自定义命令是否会严格遵循新增说明，取决于调用时是否真的读取这些文件
  - 如果后续要修正 `youtube2notion` 的“发布前确认”行为，应单独立项
- 下一步：
  - 用户审阅当前工作流文档
  - 后续新任务从 [AGENTS.md](./AGENTS.md) 和本文件开始

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
