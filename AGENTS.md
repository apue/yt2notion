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

- Claude Code / Opus：负责需求澄清、方案比较、影响面分析、验收标准定义
- Codex：负责读取代码、执行改动、运行验证、整理交接结果
- User：负责确认方向、批准高风险动作、决定是否进入发布步骤

## 启动检查

任何 agent 接手新任务时，按下面顺序执行：

1. 读取 `AGENTS.md`
2. 读取 [handoff.md](./handoff.md)
3. 查看当前 `git status` / `git diff`
4. 按需补读 [CLAUDE.md](./CLAUDE.md)、[PROJECT_MAP.md](./PROJECT_MAP.md)、[.cursorrules](./.cursorrules)

如果 `handoff.md` 为空、过期或与当前任务不一致，接手者要先补齐它，再继续执行。

## Agent 职责

### 1. Planner: Claude Code / Opus

适用场景：

- 需求不完整
- 有多个实现方案或明显 tradeoff
- 涉及架构调整、数据契约变更、性能优化、发布流程

职责：

- 澄清任务目标、非目标和验收标准
- 标出受影响文件、步骤、配置项和风险
- 明确哪些动作需要用户确认
- 在切换给 Codex 前，把执行包写入 [handoff.md](./handoff.md)

### 2. Executor: Codex

适用场景：

- 任务已经足够具体
- 或规划已完成，可直接实现

职责：

- 先读相关代码和文档，不盲改
- 只在已批准范围内改动文件
- 优先保持现有插件架构、数据契约和接口边界
- 运行必要验证，并记录结果
- 完成后更新 [handoff.md](./handoff.md)

### 3. Reviewer: Claude Code / Codex

职责：

- 先看行为风险和回归风险，再看风格问题
- 审查时优先关注：发布安全、数据契约、提示词模板、ASR/性能敏感路径、测试缺口
- Code Review的修改后只进行静态检查/本地检查，请勿执行任何需要调用远程服务（如ASR/LLM API）的操作验证

## 默认工作流

### A. 先规划，再执行

默认遵循 [CLAUDE.md](./CLAUDE.md) 的“先讨论，再动手”，并要求 Planner 在进入实现前把任务状态写入 [handoff.md](./handoff.md)：

1. Planner 复述目标
2. Planner 给出方案、tradeoff、影响范围
3. User 确认方向
4. Codex 开始实现

例外：

- 用户明确说“直接改”
- 任务已具体到文件/函数/行为级别
- 改动不涉及架构、发布或高风险外部副作用

### B. 实现阶段

Codex 执行时应遵守：

- 先读相关文件，再改动
- 不修改 `prompts/` 下模板的 Markdown 结构
- 不自动发布到 Notion
- 不做无关重构
- 保持公开函数 type hints、`typing.Protocol` 接口风格、自定义异常约定

### C. 验证阶段

按任务需要选择最小充分验证：

- `uv run pytest tests/ -v`
- `uv run ruff check src/`
- `uv run ruff format src/`
- 必要时执行更小范围测试或单文件 lint

如果没有运行验证，必须在 [handoff.md](./handoff.md) 写明原因。

## 任务切换

### Claude / Opus -> Codex

切换前，Planner 必须在 [handoff.md](./handoff.md) 写清楚：

- 任务目标
- 当前状态
- 约束和禁区
- 受影响文件
- 建议命令或验证步骤
- 验收标准
- 未决问题

只要执行包足够完整，Codex 就应直接落地，不重复做大段抽象规划。

### Codex -> Claude / Opus

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

当接手任务需要阅读代码库或大于 500 行的长文件时，**严禁使用 `nl` 配合 `sed` 进行盲目的分页通读**（如 `sed -n '1,200p'`）。这种行为极度浪费计算资源且容易丢失上下文。

在阅读和检索大文件时，必须严格遵守“先骨架，后精准切片”的原则：

1. **先看骨架 (Skeleton First)**：
   - 面对陌生大文件，必须先提取代码的结构定义（类名、函数签名），而非直接读取正文。
   - 必须优先使用 `rg -n` (ripgrep) 获取大纲与行号。
   - Python 示例：`rg -n "^(class|def|async def) " filepath.py`
   - TypeScript 示例：`rg -n "^(export |const |function |class )" filepath.ts`

2. **精准切片 (Targeted Reading)**：
   - 只有在通过骨架检索确定了目标逻辑所在的**具体行号**后，才可以提取该片段。
   - 示例：确认 `_step_summarize` 函数在第 1069 到 1224 行，执行 `sed -n '1069,1224p' filepath.py`。

3. **全域搜索优先 (Search > Read)**：
   - 如果为了寻找某个特定变量、配置项或逻辑的调用化，直接使用 `rg -n "keyword" src/` 跨文件检索，而不是把整个大文件加载进来用肉眼找。

4. **AST 与高级逻辑检索 (ast-grep/sg 强制优先)**：
   - 环境中已安装 `ast-grep` (`sg`) 工具。在检索**跨多行的函数调用**、**复杂的参数传递**、**提取完整函数体**时，严禁使用脆弱的正则 (`rg`)，必须使用 `sg` 进行结构化查询。
   - **`sg` 的基础语法约定**：使用 `$VAR` 匹配单个语法节点，使用 `$$$ARGS` 匹配多个连续节点（如多个参数或多行代码块）。
   
   - **Example 1: 查找特定方法的所有调用（无视换行和格式）**
     当排查某个函数在哪里被调用时，直接提取调用点：
     `sg -p 'summarizer.compose_guide_note($$$ARGS)' -l python src/`
     
   - **Example 2: 查找带有特定特征的函数调用**
     例如，只想找 `run_pipeline` 且其中 `dry_run` 参数被显式设置为 `True` 的地方（`$_` 表示忽略某个位置的参数）：
     `sg -p 'run_pipeline($_, $_, dry_run=True)' -l python tests/`
     
   - **Example 3: 提取某个函数的完整定义（彻底替代粗暴的 sed 切片）**
     如果你只想看某个函数的完整代码，不需要先用 rg 找行号再用 sed 截取，直接用 sg 打印完整块：
     `sg -p 'def _step_summarize($$$ARGS): $$$BODY' -l python src/yt2notion/pipeline.py`
     
   - **Example 4: 检索特定的代码模式（如异常捕获）**
     排查所有捕获了特定异常的代码块：
     `sg -p 'try: $$$TRY_BODY except ConfigError as $E: $$$CATCH_BODY' -l python src/`

### 改代码时的约束

- 公共函数和方法必须有 type hints
- 接口优先用 `typing.Protocol`
- 后端扩展通过工厂函数和 `config.yaml` backend 选择，不要绕开现有动态加载入口
- 步骤间数据传递遵守 [PROJECT_MAP.md](./PROJECT_MAP.md) 中的 JSON 契约

### 改文档时的约束

- 工作流变了：更新 `AGENTS.md`
- 结构、契约、扩展点、pipeline 事实变了：更新 [PROJECT_MAP.md](./PROJECT_MAP.md)
- 项目开发底线变了：更新 [CLAUDE.md](./CLAUDE.md) 和必要的 `.cursorrules`
- 若只改了 `AGENTS.md` / `CLAUDE.md` / `.cursorrules` 中的事实描述而未改 `PROJECT_MAP.md`，视为不合规变更

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
- 涉及 PR 流程时，优先执行可复现的命令行步骤并在交接中记录关键命令与结果。

## 任务追踪

[handoff.md](./handoff.md) 是唯一的活跃交接记录。每次切换都要更新，而不是靠聊天上下文记忆。`docs/plan.md` 可以保存详细规划，但不能替代 `handoff.md`。

建议每个任务至少记录：

- 标题
- 当前 owner
- 状态
- 目标
- 约束
- 受影响文件
- 验证结果
- 下一步

## 快速入口

- 项目规则与底线：[CLAUDE.md](./CLAUDE.md)
- 代码地图与数据契约：[PROJECT_MAP.md](./PROJECT_MAP.md)
- 工具行为与风格限制：[.cursorrules](./.cursorrules)
- 当前交接状态：[handoff.md](./handoff.md)
- Codex 基础配置：[config.toml](./config.toml)
