# Project Map (for Claude Code)

## Entry Points

| 入口 | 文件 | 说明 |
|------|------|------|
| `uv run yt2notion "URL"` | `cli.py` → `pipeline.run_pipeline()` | 主 CLI，typer 框架 |
| `python -m yt2notion.extract_cmd` | `extract_cmd.py` | Slash command 模式，JSON stdout，供 MCP 调用 |

pyproject.toml 注册入口：`yt2notion = "yt2notion.cli:app"`

## Config ↔ Code 映射

| config.yaml 路径 | 消费方 | 作用 |
|---|---|---|
| `model.backend` | `models/__init__.py:create_summarizer()` | 选择 Summarizer 实现 |
| `model.summarize_model` | Summarizer 实现的 map 阶段 | Sonnet 做逐段英文总结 |
| `model.translate_model` | Summarizer 实现的 reduce 阶段 | Opus 做中文化 |
| `model.review_model` | `models/llm.py:create_llm_caller()` | Haiku 做章节提取/校对/分段 |
| `storage.backend` | `storage/__init__.py:create_storage()` | 选择 Storage 实现 |
| `storage.notion.*` | `storage/notion.py:NotionStorage.__init__()` | token / database_id / parent_page_id / directory_rules |
| `extract.subtitle_priority` | `extract.py:extract_subtitles()` | 字幕语言优先级 |
| `extract.asr.backend` | `transcribe/__init__.py:create_transcriber()` | 选择 ASR 实现 |
| `extract.asr.endpoint` | `transcribe/remote.py:RemoteTranscriber` | ASR 服务地址（或 `ASR_ENDPOINT` 环境变量） |
| `output.max_segment_seconds` | `pipeline.py` Step 2 + `topic_segment.py` | 触发段落拆分的阈值 |
| `output.long_content_threshold_seconds` | `pipeline.py` Step 5 | 短内容单 pass vs 长内容 map-reduce 的分界 |
| `output.chunk_duration_seconds` | `process.py` | 时间戳绑定的 chunk 粒度 |
| `workspace.base_dir` | `workspace.py:Workspace` | 中间产物存放目录 |

config 加载：`config.py:load_config()` → 读 YAML → deep merge with DEFAULTS → 校验 backend 合法 → 返回 `AppConfig` dataclass。

## Factory Functions（动态加载）

所有 backend 通过 if/elif 工厂函数加载，没有注册表：

| Factory | 位置 | config 字段 | 当前实现 |
|---|---|---|---|
| `create_summarizer(config)` | `models/__init__.py` | `model.backend` | `claude_code` → ClaudeCodeModel, `anthropic_api` → AnthropicAPIModel |
| `create_storage(config)` | `storage/__init__.py` | `storage.backend` | `notion` → NotionStorage, `obsidian` → ObsidianStorage(stub) |
| `create_transcriber(config)` | `transcribe/__init__.py` | `extract.asr.backend` | `remote` → RemoteTranscriber |
| `create_llm_caller(config, model_key=)` | `models/llm.py` | `model.backend` + `model.{model_key}` | `claude_code` → ClaudeCodeCaller |

## 步骤间数据契约

Pipeline 步骤通过 Workspace JSON 文件传递数据：

```
Step 1 → metadata.json   : VideoMeta dataclass (models/base.py)
Step 2 → segments.json    : list[{title, start_seconds, end_seconds}]
Step 3 → transcripts.json : list[{title, start_seconds, end_seconds, text, source}]
                            source = "subtitle" | "asr"
Step 4 → reviewed.json    : 同 transcripts 结构，text 被 Haiku 校对过
Step 5 → summary.json     : ChineseContent {overview, key_points[{timestamp, title, summary}], tags, raw_markdown, ?mindmap}
```

所有数据模型定义在 `models/base.py`：VideoMeta, Chapter, Summary, ChunkSummary, ChineseContent 等。

## Prompt 模板 ↔ 代码绑定

加载机制：`prompts/__init__.py` 的 `render_prompt(name, **kwargs)` 用 `str.replace("{key}", value)` 做模板替换（不用 str.format，避免和 JSON 示例冲突）。

| 模板文件 | 调用方 | 模型 | 模板变量 |
|---|---|---|---|
| `extract_chapters.md` | `chapter_extract.py` | Haiku | `{total_duration}` |
| `topic_segment.md` | `topic_segment.py` | Haiku | (无变量) |
| `review.md` | `review.py` | Haiku | `{title}`, `{channel}` |
| `summarize.md` | Summarizer (短内容+有章节) | Sonnet | (无变量) |
| `summarize_freeform.md` | Summarizer (短内容+无章节) | Sonnet | (无变量) |
| `summarize_chunk.md` | Summarizer map 阶段 | Sonnet | `{segment_title}`, `{start_time}`, `{end_time}`, `{segment_index}`, `{total_segments}` |
| `chinese.md` | Summarizer.to_chinese() | Opus | (无变量) |
| `synthesize.md` | Summarizer.synthesize() | Opus | `{title}`, `{channel}`, `{duration}`, `{url}` |

## 扩展 Checklist

### 加新 model backend（如 OpenAI）

1. `src/yt2notion/models/openai_api.py` — 实现 `Summarizer` protocol
2. `src/yt2notion/models/__init__.py` — `create_summarizer()` 加 elif 分支
3. `src/yt2notion/models/llm.py` — `create_llm_caller()` 加 elif 分支（如果需要轻量调用）
4. `src/yt2notion/config.py` — `VALID_MODEL_BACKENDS` 加新值
5. `config.example.yaml` — 注释说明新选项

### 加新 storage backend（如 Obsidian）

1. `src/yt2notion/storage/obsidian.py` — 实现 `Storage` protocol 的 `save()` 方法
2. `src/yt2notion/storage/__init__.py` — `create_storage()` 加 elif 分支
3. `src/yt2notion/config.py` — `VALID_STORAGE_BACKENDS` 加新值（如果还没有）
4. `config.example.yaml` — 加 obsidian section

### 加新 ASR backend

1. `src/yt2notion/transcribe/new_backend.py` — 实现 `Transcriber` protocol
2. `src/yt2notion/transcribe/__init__.py` — `create_transcriber()` 加 elif 分支
3. `config.example.yaml` — 加 asr backend 选项

### 加新 prompt 模板

1. `src/yt2notion/prompts/new_template.md` — 写模板，用 `{var}` 占位
2. 调用方用 `render_prompt("new_template", var=value)` 加载

### 改 pipeline 步骤逻辑

主要编辑 `pipeline.py`。每步对应一个内部函数（`_step_download`, `_step_segment` 等）。步骤间通过 workspace JSON 解耦，可以独立修改单步不影响其他步。

## 关键依赖关系

```
cli.py → config.py, pipeline.py
pipeline.py → extract.py, process.py, workspace.py,
              chapter_extract.py, segment.py, topic_segment.py, review.py,
              models/__init__.py, storage/__init__.py, transcribe/__init__.py
chapter_extract.py, review.py, topic_segment.py → models/llm.py (LLMCaller), prompts/
models/claude_code.py, models/anthropic_api.py → prompts/, models/_parsers.py
models/_parsers.py → models/base.py (data classes)
storage/notion.py → notion_client (外部库)
transcribe/remote.py → httpx (外部库)
extract.py → subprocess (yt-dlp CLI)
audio.py → subprocess (ffmpeg/ffprobe CLI)
models/llm.py ClaudeCodeCaller → subprocess (claude CLI)
```
