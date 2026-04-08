# handoff.md

本文件用于在 User、Claude Code、Opus、Codex 之间交接任务。任何 agent 接手前先读这里；任何 agent 离开前更新这里。它是当前任务的唯一活跃状态面板，不能被聊天上下文或 `docs/plan.md` 替代。

## 当前任务卡

- 任务：将 agent 默认 pipeline 配置迁移到 `~/.yt2notion-agent/config.yaml`，并初始化本机 runtime config
- 状态：`done`
- 当前 owner：User
- 上一执行者：User
- 下一执行者：User / Reviewer
- 来源：用户确认 agent 不应继续隐式依赖 repo 根目录 `config.yaml`，要求一次性改完代码、文档和本机 runtime 配置
- 目标：
  - `uv run yt2notion agent ...` 默认读取 `~/.yt2notion-agent/config.yaml` 作为 pipeline 配置
  - `~/.yt2notion-agent/agent.yaml` 继续只承载 runtime control plane
  - `agent init` 自动生成 runtime `config.yaml`
  - 显式 `--config` 仍然优先覆盖默认路径
  - 初始化本机 `~/.yt2notion-agent/config.yaml`：保留当前 remote ASR endpoint / restart 配置不变，补入 `groq` primary + `remote` fallback，Groq key 留空
- 非目标：
  - 不把完整 pipeline 配置并入 `agent.yaml`
  - 不改变 `process` / `prepare` 主 CLI 的 `config.yaml` 默认语义
  - 不变更 remote ASR 服务部署方式、endpoint 或 restart command
- 约束：
  - pipeline/contract 事实以 `PROJECT_MAP.md` 为准
  - `agent.yaml` 与 runtime `config.yaml` 的职责必须分离
  - 默认路径必须与 `agent_home` 对齐，不能继续依赖当前工作目录
  - 不把真实 Groq key 写入仓库或本机 runtime config
- 受影响文件：
  - [src/yt2notion/agent_runtime.py](./src/yt2notion/agent_runtime.py)
  - [src/yt2notion/cli.py](./src/yt2notion/cli.py)
  - [tests/test_agent_runtime.py](./tests/test_agent_runtime.py)
  - [tests/test_cli.py](./tests/test_cli.py)
  - [PROJECT_MAP.md](./PROJECT_MAP.md)
  - [README.md](./README.md)
  - [handoff.md](./handoff.md)
- 验收标准：
  - `agent init` 会生成 `~/.yt2notion-agent/config.yaml`
  - `agent add/run/retry/_worker` 在未传 `--config` 时默认使用 `<agent_home>/config.yaml`
  - 显式 `--config` 仍可覆盖默认路径
  - `README.md` / `PROJECT_MAP.md` 同步新的 config 查找语义
  - 本机 `~/.yt2notion-agent/config.yaml` 已存在并写入目标配置
- 建议命令：
  - `uv run pytest tests/test_agent_runtime.py tests/test_cli.py -q`
  - `uv run ruff check src/yt2notion/agent_runtime.py src/yt2notion/cli.py tests/test_agent_runtime.py tests/test_cli.py`
- 未决问题：
  - 无

## 当前执行记录

- 已完成：
  - 用户已确认采用“双文件”方案：
    - `~/.yt2notion-agent/agent.yaml` 只保留 runtime control plane
    - `~/.yt2notion-agent/config.yaml` 承载完整 pipeline 配置
  - 已确认当前本机默认运行路径：
    - runtime home: `~/.yt2notion-agent`
    - runtime agent config: `~/.yt2notion-agent/agent.yaml`
    - 当前被 `agent` 默认命中的 base config 是 repo 根目录 `config.yaml`
  - 已完成代码改造：
    - `ensure_agent_home()` 现在会创建 `runtime_config_path = <agent_home>/config.yaml`
    - `agent add` / `agent run` / `agent retry` / `agent _worker` 在未传 `--config` 时默认解析到 `<agent_home>/config.yaml`
    - 显式 `--config` 仍优先覆盖默认路径
    - `process` / `prepare` 的默认 `config.yaml` 语义未改
  - 已完成文档同步：
    - `README.md` 已补 runtime 双配置文件说明与默认 config 查找规则
    - `PROJECT_MAP.md` 已把 `agent.yaml` / `config.yaml` 分工和默认路径写成 canonical truth
  - 已完成本机 runtime 配置初始化：
    - 已创建 `~/.yt2notion-agent/config.yaml`
    - 内容已切成 `groq primary + remote fallback`
    - 现有 remote ASR endpoint / restart 配置保持不变
    - Groq `api_key` 留空，等待用户自行填写
  - 已提交并推送分支：
    - branch: `feat/groq-asr-fallback`
    - commit: `03c4835`
    - PR: `#16`
- 当前阻塞：
  - 无代码阻塞
  - Groq key 仍为空，实际 agent 转写在填写 key 前不会通过 config 校验
- 已修改文件：
  - [src/yt2notion/agent_runtime.py](./src/yt2notion/agent_runtime.py)
  - [src/yt2notion/cli.py](./src/yt2notion/cli.py)
  - [tests/test_agent_runtime.py](./tests/test_agent_runtime.py)
  - [tests/test_cli.py](./tests/test_cli.py)
  - [PROJECT_MAP.md](./PROJECT_MAP.md)
  - [README.md](./README.md)
  - [handoff.md](./handoff.md)
- 已运行验证：
  - `uv run pytest tests/test_agent_runtime.py tests/test_cli.py -q` → `45 passed`
  - `uv run ruff check src/yt2notion/agent_runtime.py src/yt2notion/cli.py tests/test_agent_runtime.py tests/test_cli.py` → pass
  - `uv run pytest tests/test_agent_runtime.py tests/test_config.py tests/test_transcribe_base.py tests/test_transcribe_groq.py tests/test_transcribe_factory.py tests/test_workspace.py tests/test_pipeline.py tests/test_agent_worker.py tests/test_cli.py -q` → `154 passed, 4 warnings`
  - `uv run ruff check src/yt2notion/agent_runtime.py src/yt2notion/agent_worker.py src/yt2notion/cli.py src/yt2notion/pipeline.py src/yt2notion/transcribe/__init__.py src/yt2notion/transcribe/groq.py src/yt2notion/workspace.py tests/test_agent_runtime.py tests/test_agent_worker.py tests/test_cli.py tests/test_pipeline.py tests/test_transcribe_base.py tests/test_transcribe_factory.py tests/test_transcribe_groq.py tests/test_workspace.py` → pass
  - `~/.yt2notion-agent/config.yaml` YAML parse → pass
- 风险/回滚点：
  - 这次会改动本机 `~/.yt2notion-agent/` 下的实际 runtime 文件
  - 如果用户长期同时维护 repo 根目录 `config.yaml` 和 runtime `~/.yt2notion-agent/config.yaml`，两者可能漂移；agent 路径以后只看 runtime 文件
- 下一步：
  - 用户在 `~/.yt2notion-agent/config.yaml` 填入 Groq key
  - 之后继续使用 agent 时无需再传 `--config`

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
