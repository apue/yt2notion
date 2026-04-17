# AGENTS.md

本文件是 `yt2notion` 仓库的协作入口，用来统一 User、Claude Code、Opus、Codex 之间的任务流转方式。任何 agent 开始任务前，先读本文件，再读 [handoff.md](./handoff.md)，最后按需回看 [CLAUDE.md](./CLAUDE.md)、[PROJECT_MAP.md](./PROJECT_MAP.md) 和 [.cursorrules](./.cursorrules)。其中，代码结构、数据契约与 pipeline 事实以 [PROJECT_MAP.md](./PROJECT_MAP.md) 为唯一锚点。

## 文档优先级

1. 用户当前指令
2. `AGENTS.md`
3. [CLAUDE.md](./CLAUDE.md)
4. [PROJECT_MAP.md](./PROJECT_MAP.md)
5. [.cursorrules](./.cursorrules)

如果文档之间有冲突，按下面规则处理：

- 工作流、角色分工、交接格式：以 `AGENTS.md` 为准
- 项目约束、开发底线、命令约定：以 `CLAUDE.md` 为准
- 代码结构、数据契约、扩展入口、pipeline 事实：以 `PROJECT_MAP.md` 为准
- 工具行为、编码风格、执行限制：以 `.cursorrules` 为准
- 若文档之间对 pipeline 描述不一致，以 `PROJECT_MAP.md` 为准；`.cursorrules` 只作为压缩摘要

## 文档锚定约定（强制）

- `PROJECT_MAP.md` 是唯一事实锚点：步骤顺序、分支逻辑、artifact 契约、config↔code 映射、扩展入口都只在这里定义。
- `AGENTS.md`、`CLAUDE.md`、`.cursorrules` 只做索引与约束摘要，不重复维护完整 pipeline 事实。
- 当实现变化影响 pipeline/契约时，必须先更新 `PROJECT_MAP.md`，再同步其余三个文档中的摘要/索引。
- 若摘要与锚点冲突，执行和评审一律以 `PROJECT_MAP.md` 为准。

## 项目概述

`yt2notion` 是一个媒体内容处理 CLI 管道：输入 YouTube / Podcast URL，经过字幕提取或 ASR、章节/话题切分、转录校对、实体提取、总结与发布，最终输出到 Notion 或 Obsidian。完整的 pipeline、artifact 与分支规则以 [PROJECT_MAP.md](./PROJECT_MAP.md) 为准。

默认分工如下：

- Codex：默认主执行者与任务 owner；负责读取代码和文档、提出必要澄清、执行改动、运行最小充分验证、创建或更新分支/PR、处理 review comments、整理交接结果
- Claude Code / Opus：按需担任 Planner / Reviewer；仅在需求不完整、存在明显 tradeoff、涉及架构调整或高风险流程时介入
- User：负责确认方向、批准高风险动作、决定是否合入 `main` 或进入发布步骤

## 启动检查

任何 agent 接手新任务时，按下面顺序执行：

1. 读取 `AGENTS.md`
2. 读取 [handoff.md](./handoff.md)
3. 查看当前 `git status` / `git diff`
4. 按需补读 [CLAUDE.md](./CLAUDE.md)、[PROJECT_MAP.md](./PROJECT_MAP.md)、[.cursorrules](./.cursorrules)

如果 `handoff.md` 为空、过期或与当前任务不一致，接手者要先补齐它，再继续执行。

## Agent 职责

### 1. Planner: Codex 默认承担，Claude Code / Opus 按需介入

适用场景：

- 需求不完整
- 有多个实现方案或明显 tradeoff
- 涉及架构调整、数据契约变更、性能优化、发布流程

职责：

- 澄清任务目标、非目标和验收标准
- 标出受影响文件、步骤、配置项和风险
- 明确哪些动作需要用户确认
- 如果实现前需要规划，先把执行包写入 [handoff.md](./handoff.md)，再进入实现

### 2. Executor: Codex（默认）

适用场景：

- 任务已经足够具体
- 或规划已完成，可直接实现

职责：

- 先读相关代码和文档，不盲改
- 只在已批准范围内改动文件
- 优先保持现有插件架构、数据契约和接口边界
- 运行必要验证，并记录结果
- 按仓库规定维护分支、PR、review 和交接状态
- 完成后更新 [handoff.md](./handoff.md)

### 3. Reviewer: `/review` + Claude Code / Codex

职责：

- 代码改动优先通过 `/review` 执行正式 code review；需要补充分析时再由 Claude Code / Codex 继续审查
- 先看行为风险和回归风险，再看风格问题
- 审查时优先关注：发布安全、数据契约、提示词模板、ASR/性能敏感路径、测试缺口
- Code Review的修改后只进行静态检查/本地检查，请勿执行任何需要调用远程服务（如ASR/LLM API）的操作验证

## 默认工作流

### A. 任务入口：默认由 Codex 先判断是否需要规划

默认流程如下：

1. Codex 先读取文档、`handoff.md` 和相关代码，判断任务是否已足够具体
2. 如果任务具体且不涉及架构分叉、发布风险或高风险外部副作用，Codex 直接实现
3. 如果需求不完整，或存在明显方案 tradeoff / 架构影响 / 发布风险，由 Codex 或 Claude Code / Opus 先完成规划，并写入 [handoff.md](./handoff.md)
4. 需要用户决策的点先确认，随后由 Codex 进入实现和验证

### B. GitHub 交付 Workflow

分类规则：

- 纯文本改动：只修改文档、注释或说明性文本，不改变运行时行为、数据契约、CLI 结果或测试结果
- 代码改动：任何会影响运行时行为、配置解析、数据产物、CLI 输出、测试结果或 review 风险的改动，都按代码改动处理

纯文本改动流程：

1. 创建 git 分支
2. 本地自查 diff、链接、Markdown 渲染或文本一致性
3. 使用 `gh` 创建 PR
4. 审阅无误后合入 `main`

代码改动流程：

1. 创建 git 分支
2. 先完成最小充分自测
3. 使用 `gh` 创建 PR
4. 通过 `/review` 执行 code review
5. 修复 review comments
6. 再次运行受影响范围的自测
7. 更新 PR
8. 审阅无误后合入 `main`

补充规则：

- 默认不直接在 `main` 上开发，也不绕过 PR 直接合并
- 代码改动在创建 PR 前必须先有本地自测结果；修复 review comments 后必须重新自测
- `/review` 后的修复验证只做本地检查和本地测试，不调用远程 ASR / LLM 服务
- 是否最终合入 `main` 由 User 决定

### C. 实现阶段

Codex 执行时应遵守：

- 先读相关文件，再改动
- 不修改 `prompts/` 下模板的 Markdown 结构
- 不自动发布到 Notion
- 不做无关重构
- 保持公开函数 type hints、`typing.Protocol` 接口风格、自定义异常约定

### D. 验证阶段

按任务需要选择最小充分验证：

- 纯文本改动至少检查 diff、链接、格式和关键描述是否一致
- `uv run pytest tests/ -v`
- `uv run ruff check src/`
- `uv run ruff format src/`
- 必要时执行更小范围测试或单文件 lint

如果没有运行验证，必须在 [handoff.md](./handoff.md) 写明原因。

## 任务切换

### Planner -> Codex

切换前，Planner 必须在 [handoff.md](./handoff.md) 写清楚：

- 任务目标
- 当前状态
- 约束和禁区
- 受影响文件
- 建议命令或验证步骤
- 验收标准
- 未决问题

只要执行包足够完整，Codex 就应直接落地，不重复做大段抽象规划。

### Codex -> Planner / Reviewer

以下情况切回 Planner：

- 发现需求与现状冲突
- 需要在多个方案中做产品/架构选择
- 触及发布、凭证、外部服务写入、破坏性 git 操作
- 遇到未记录的数据契约变更

切换时，Codex 必须在 [handoff.md](./handoff.md) 更新：

- 已完成内容
- 当前阻塞点
- 已修改文件
- 已运行验证
- 建议下一步

### 中途接手规则

- 同一时间只指定一个主要执行者
- 接手前先读 `git diff` 和 [handoff.md](./handoff.md)
- 未读清上下文前，不覆盖别人刚改过的文件
- 并行工作时，必须按文件或模块划分写入边界

## 文件生成与修改规则

### 必须遵守

- 所有输出都保留来源信息：频道名、标题、URL
- 未经用户确认，不进入自动发布
- `prompts/` 下 `.md` 是 prompt template，不按普通文档改格式
- 性能敏感改动，尤其 ASR 管道，必须附 benchmark 依据

### 读代码时的约束
## 大文件与代码阅读约束 (Large File Reading Constraints)

当阅读代码或排查问题时，请优先调用 code-exploration skill 进行智能代码检索。

### 改代码时的约束

- 公共函数和方法必须有 type hints
- 接口优先用 `typing.Protocol`
- 后端扩展通过工厂函数和 `config.yaml` backend 选择，不要绕开现有动态加载入口
- 步骤间数据传递遵守 [PROJECT_MAP.md](./PROJECT_MAP.md) 中的 JSON 契约

### 改文档时的约束

- 工作流变了：更新 `AGENTS.md`
- 开发底线、命令约定、验证门槛变了：更新 [CLAUDE.md](./CLAUDE.md) 和必要的 `.cursorrules`
- 结构、契约、扩展点、pipeline 事实变了：更新 [PROJECT_MAP.md](./PROJECT_MAP.md)
- 只有当变更触及 pipeline / 契约 / 扩展点事实时，才要求同步更新 [PROJECT_MAP.md](./PROJECT_MAP.md)

## Sandbox 与审批边界

无论运行时给了多大权限，Codex 都应把默认边界限制在当前仓库内。

以下操作必须停下来等待用户明确确认：

- 发布到 Notion / Obsidian
- 修改密钥、账号、外部服务配置
- 删除大量文件或执行破坏性 git 操作
- 改动性能敏感路径但没有 benchmark 证据
- 超出当前任务范围的跨目录重构

如果运行环境本身更严格，以运行环境限制为准。

## GitHub 工具约定

- 本仓库默认使用 `gh` CLI 完成 GitHub 相关流程（PR 创建、评论、查看 checks、触发 workflow）。
- 不默认依赖 GitHub App / Connector；仅在 `gh` 不可用或用户明确要求时才使用。
- 代码改动的 PR 在创建后默认通过 `/review` 执行 code review，再进入 comment 修复与复测流程。
- 涉及 PR 流程时，优先执行可复现的命令行步骤，并在交接中记录分支名、PR 编号/链接、review 状态和最后一次自测结果。

## 任务追踪

[handoff.md](./handoff.md) 是唯一的活跃交接记录。每次切换都要更新，而不是靠聊天上下文记忆。`docs/plan.md` 可以保存详细规划，但不能替代 `handoff.md`。

建议每个任务至少记录：

- 标题
- 当前 owner
- 状态
- 分支名
- PR 编号或链接
- review 状态
- 目标
- 约束
- 受影响文件
- 验证结果
- 最后一次自测命令
- 下一步

## 快速入口

- 项目规则与底线：[CLAUDE.md](./CLAUDE.md)
- 代码地图与数据契约：[PROJECT_MAP.md](./PROJECT_MAP.md)
- 工具行为与风格限制：[.cursorrules](./.cursorrules)
- 当前交接状态：[handoff.md](./handoff.md)
- Codex 基础配置：[config.toml](./config.toml)
