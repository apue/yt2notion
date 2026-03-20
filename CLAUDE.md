# yt2notion

YouTube 视频字幕提取 → LLM 总结 → Notion 发布的 CLI 管道工具。

## Tech Stack

- Python 3.11+, uv 包管理
- yt-dlp 字幕提取
- Anthropic Claude（通过 `claude -p` 或 API）
- Notion API 发布
- typer CLI 框架

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

Plugin 架构，两个抽象接口用 `typing.Protocol` 定义：

- `models/base.py` → `Summarizer` Protocol：LLM 总结 + 中文化
- `storage/base.py` → `Storage` Protocol：保存到 Notion / Obsidian / ...

实现通过 `config.yaml` 的 `backend` 字段选择，运行时动态加载。

关键管道：`extract → process → summarize(sonnet) → to_chinese(opus) → publish`

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

<important>
- ALWAYS include source credit in output: channel name, video title, URL
- NEVER auto-publish without user confirmation step
- prompts/ 目录下的 .md 文件是 prompt template，不是文档，不要修改格式
</important>

## Project References

- @README.md 项目介绍和使用说明
- @config.example.yaml 配置文件模板
