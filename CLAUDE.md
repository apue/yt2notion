# yt2notion

媒体内容（YouTube 视频、Podcast 等）→ 字幕/转写 → LLM 总结 → Notion / Obsidian 发布的 CLI 管道工具。

## Working Style

**先讨论，再动手。** 收到新任务或功能需求时：
1. 先说明你的理解，列出可能的方案和 tradeoff
2. 如果信息不够，主动提问——不要假设
3. 等我确认方向后再写代码或改文件
4. 涉及架构变更时，先画清楚影响范围

例外：如果我明确说"直接改"或给出了足够具体的指令（如 "把 X 函数的返回类型从 A 改成 B"），可以直接执行。

开始任何任务前，先执行下面的启动检查：

1. 读取 `AGENTS.md`
2. 读取 `handoff.md`
3. 再按需查阅 `PROJECT_MAP.md`、`.cursorrules` 和相关代码

如果当前任务要切换给 Codex，或从 Codex 接回 Claude/Opus，必须先更新 `handoff.md`，写明当前状态、受影响文件、约束、验证结果和下一步。

## Tech Stack

- Python 3.11+, uv 包管理
- yt-dlp 字幕提取
- Anthropic Claude（通过 `claude -p` 或 API）
- Notion API 发布
- typer CLI 框架
- mlx-whisper / Qwen ASR（Podcast 转写，本地 Mac Mini 运行）

## Commands

```bash
uv sync                        # 安装依赖
uv sync --extra notion         # 安装 Notion 可选依赖
uv sync --extra anthropic      # 安装 API 可选依赖
uv run yt2notion "URL"         # 运行
uv run pytest tests/ -v        # 测试
uv run ruff check src/         # lint
uv run ruff format src/        # format
```

## Architecture

Plugin 架构，三个抽象接口用 `typing.Protocol` 定义：
- `models/base.py` → `Summarizer` Protocol：多步 LLM 总结 + 中文化（Sonnet map / Opus reduce）
- `models/llm.py` → `LLMCaller` Protocol：轻量一次性 LLM 调用（章节提取 / 转录校对 / 话题分段）
- `storage/base.py` → `Storage` Protocol：保存到 Notion / Obsidian（已实现） / ...

实现通过 `config.yaml` 的 `backend` 字段选择，运行时动态加载。当前 `LLMCaller` 仅有 `ClaudeCodeCaller` 实现。

流水线的唯一规范真源在 [PROJECT_MAP.md](./PROJECT_MAP.md)。本文件只保留开发者视角的高层摘要：
- `PROJECT_MAP.md` 负责步骤顺序、条件分支、JSON 契约、prompt 绑定和扩展入口
- `CLAUDE.md` 负责开发约束、命令约定、模型角色与本地运行假设
- 当实现和文档发生偏差时，以 `PROJECT_MAP.md` 为准，再回头同步这里的摘要

文档锚定约定：
- `AGENTS.md` / `CLAUDE.md` / `.cursorrules` 仅做索引与规则，不承载完整 pipeline 事实。
- 任何涉及 pipeline、契约、扩展点的变更，先改 `PROJECT_MAP.md`，再改本文件摘要。

模型角色只保留到“用途级”：
- 章节提取、转录校对、话题分段使用 `LLMCaller`
- 多步总结使用 `Summarizer`
- ASR 使用本地 `mlx-whisper / Qwen` 路径

## Code Style

- Python 3.11+ 类型标注，所有公开函数必须有 type hints
- 用 `typing.Protocol` 做接口，不用 ABC
- ruff 做 lint 和 format（已配置在 pyproject.toml）
- 测试用 pytest，fixture 放 `tests/conftest.py`
- 错误处理用自定义异常类，定义在各模块内

## Key Design Decisions

- `claude -p --max-turns 1` 调用 CC 时禁止 agentic 行为，只做文本处理
- 字幕优先级：zh-Hans > zh-Hant > en (manual) > en (auto)
- Sonnet 做英文总结 + 结构提取，Opus 做中文化润色（非逐字翻译）
- 时间戳在预处理阶段绑定到 chunk，不依赖 LLM 猜测
- Podcast ASR 在本地运行（Mac Mini + mlx-whisper/Qwen），不走云端 API

<important>
- ALWAYS include source credit in output: channel name, video title/episode title, URL
- NEVER auto-publish without user confirmation step
- prompts/ 目录下的 .md 文件是 prompt template，不是文档，不要修改格式
- 性能敏感的改动（特别是 ASR 管道）需要有 benchmark 数据支持，不要凭感觉优化
</important>

## Project References

- @AGENTS.md 仓库级协作规则、角色分工、交接流程
- @handoff.md 当前任务状态与交接面板
- @PROJECT_MAP.md 项目导航地图（config↔code 映射、扩展 checklist、数据契约、依赖关系）
- @README.md 项目介绍和使用说明
- @config.example.yaml 配置文件模板
