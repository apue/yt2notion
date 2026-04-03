# handoff.md

本文件用于在 User、Claude Code、Opus、Codex 之间交接任务。任何 agent 接手前先读这里；任何 agent 离开前更新这里。它是当前任务的唯一活跃状态面板，不能被聊天上下文或 `docs/plan.md` 替代。

## 当前任务卡

- 任务：以 `PROJECT_MAP.md` 为锚点收敛文档 single source of truth，并采用 subagent 并行落地
- 状态：`done`
- 当前 owner：Codex
- 上一执行者：User
- 下一执行者：User
- 来源：用户要求把 `PROJECT_MAP.md` 设为所有活跃文档共享的唯一锚点，并在完成后提交到当前分支
- 目标：
  - 明确 `PROJECT_MAP.md` 是 pipeline / contract / extension truth 的 canonical anchor
  - 让其他活跃文档只保留角色化摘要，不再竞争性复述完整流程真相
  - 为未来把 `PROJECT_MAP.md` 拆成索引 + part 的模式预留治理规则
- 非目标：
  - 不改代码行为
  - 不清理历史 plan/spec 文档
  - 不触碰 `prompts/` 模板
- 约束：
  - 并行工作按文件边界切分，避免 worker 冲突
  - 活跃文档必须明确 `PROJECT_MAP` 的权威性
  - 摘要文档仍需保留各自面向的读者价值，不能只剩空链接
- 受影响文件：
  - [PROJECT_MAP.md](./PROJECT_MAP.md)
  - [AGENTS.md](./AGENTS.md)
  - [CLAUDE.md](./CLAUDE.md)
  - [.cursorrules](./.cursorrules)
  - [README.md](./README.md)
  - [handoff.md](./handoff.md)
- 验收标准：
  - `PROJECT_MAP.md` 明确声明自身为 canonical anchor，并定义未来拆分规则
  - `AGENTS.md`、`CLAUDE.md`、`.cursorrules`、`README.md` 不再独立承载完整 pipeline truth
  - `PROJECT_MAP.md` 的 pipeline、branch rules、artifact contracts 与当前实现对齐
  - 改动已提交到当前分支
- 建议命令：
  - `git diff -- AGENTS.md CLAUDE.md PROJECT_MAP.md .cursorrules README.md handoff.md`
  - `git status --short`
- 未决问题：
  - 本轮先不新建 `docs/project-map/`，只在 `PROJECT_MAP.md` 中约定未来拆分机制

## 当前执行记录

- 已完成：
  - 读取 `AGENTS.md`、`handoff.md`、`CLAUDE.md`、`PROJECT_MAP.md`、`.cursorrules` 并核对当前实现
  - 确认问题本质不是“改一句文案”，而是消除多份活跃文档并行承载完整 pipeline 真相
  - 启动 subagent 并按文件边界切分：`CLAUDE.md/.cursorrules` 与 `AGENTS.md/README.md`
  - `PROJECT_MAP.md` 已升级为 canonical anchor，补齐 pipeline 顺序、branch rules、workspace artifacts、future split rule
  - `CLAUDE.md` 与 `.cursorrules` 已改为保留开发约束与政策摘要，不再复述完整流程
  - `AGENTS.md` 与 `README.md` 已改为显式指向 `PROJECT_MAP.md`
  - 所有文档改动已提交到当前分支
- 当前阻塞：
  - 无
- 已修改文件：
  - [PROJECT_MAP.md](./PROJECT_MAP.md)
  - [AGENTS.md](./AGENTS.md)
  - [CLAUDE.md](./CLAUDE.md)
  - [.cursorrules](./.cursorrules)
  - [README.md](./README.md)
  - [handoff.md](./handoff.md)
- 已运行验证：
  - `git status --short`
  - `git log --oneline --decorate -n 8`
  - `rg -n "Pipeline|pipeline|PROJECT_MAP|single truth|canonical|chapters >|Topic segmentation|7-step|5-step" AGENTS.md CLAUDE.md PROJECT_MAP.md .cursorrules README.md docs -S`
  - `git diff -- AGENTS.md README.md`
  - `git show --stat --summary --oneline ea7643b`
- 风险/回滚点：
  - `PROJECT_MAP.md` 现在信息密度更高，后续如果继续扩张，应按本轮约定及时拆成 canonical parts
  - 历史 spec / plan 文档仍可能保留旧表述，但它们不再是活跃真源
  - 若后续改 pipeline 未同步 `PROJECT_MAP.md`，仍会再次漂移
- 下一步：
  - 新的 pipeline / contract 变更先改 `PROJECT_MAP.md`
  - 等 `PROJECT_MAP.md` 超过可维护阈值时，再拆到 `docs/project-map/*.md`

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
