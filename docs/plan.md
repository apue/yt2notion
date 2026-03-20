# yt2notion 开发计划

基于现有骨架代码，逐步实现完整管道。每一步都保证可独立测试，最终用 Claude Code 执行端到端验证。

---

## Phase 1: 数据模型补全与字幕处理（纯逻辑，无外部依赖）

### Step 1.1 — 补全 `models/base.py` 数据模型

已有 `VideoMeta`, `Section`, `Summary`, `ChineseContent` 和 `Summarizer` Protocol。
`test_models.py` 引用了 `TimestampedSection`（尚未定义），需对齐。

- [ ] **文件**: `src/yt2notion/models/base.py`
  - 新增 `TimestampedSection` dataclass（`title`, `timestamp_seconds`, `content`）
  - 添加 `timestamp_display` property（秒 → `M:SS` 格式）
  - 添加 `youtube_link(video_id) -> str` 方法
  - 确认 `VideoMeta.upload_date` 设为可选（default `""`）
- [ ] **测试**: `tests/test_models.py`（已有骨架，确保 pass）
  - `test_timestamp_display` / `test_timestamp_display_zero` / `test_youtube_link` / `test_video_meta`
- **验证**: `uv run pytest tests/test_models.py -v`
- **依赖**: 无

### Step 1.2 — 配置加载模块

- [ ] **新建**: `src/yt2notion/config.py`
  - `load_config(path: str) -> dict`：读取 YAML，合并默认值
  - `class AppConfig`（dataclass）：强类型配置对象，包含 `model`, `storage`, `extract`, `credit`, `output` 各段
  - 缺少 config 文件时抛出 `ConfigError`
  - 字段验证：`backend` 值必须在已知列表中
- [ ] **新建**: `tests/test_config.py`
  - `test_load_valid_config`：用 `tmp_path` 写入 YAML 验证解析
  - `test_missing_config_raises`：文件不存在时抛异常
  - `test_default_values`：省略可选字段时填充默认值
  - `test_invalid_backend`：非法 backend 值报错
- **验证**: `uv run pytest tests/test_config.py -v`
- **依赖**: 无

### Step 1.3 — 字幕解析与分段 (`process.py`)

- [ ] **文件**: `src/yt2notion/process.py`
  - `parse_srt(path: Path) -> list[SubtitleEntry]`：用 `pysrt` 解析 SRT
  - `parse_vtt(path: Path) -> list[SubtitleEntry]`：解析 WebVTT 格式
  - `parse_subtitle_file(path: Path) -> list[SubtitleEntry]`：根据后缀分派
  - `SubtitleEntry` dataclass：`start_seconds: float`, `end_seconds: float`, `text: str`
  - `clean_text(text: str) -> str`：去 HTML 标签、去重复行、合并连续空白
  - `chunk_by_time(entries, chunk_seconds=120) -> list[Chunk]`：按时间窗口分段
  - `Chunk` dataclass：`start_seconds: int`, `text: str`
  - `format_chunks(chunks, video_id) -> str`：生成 `[CHUNK start=MM:SS]` 格式文本，供 prompt 使用
- [ ] **测试**: `tests/test_process.py`（已有注释骨架，实现以下）
  - `test_parse_srt(sample_srt)`：4 条 entry，验证时间和文本
  - `test_parse_vtt(sample_vtt)`：同上，与 SRT 输出一致
  - `test_clean_text`：HTML 标签、`\n` 重复、多余空格
  - `test_chunk_by_time`：用 conftest 中的 sample，chunk_seconds=120 → 至少 3 个 chunk
  - `test_chunk_boundary`：验证边界条件（恰好在切分点的 entry）
  - `test_empty_subtitle`：空文件 → 空列表
  - `test_unicode_subtitle`：CJK 字符正确保留
  - `test_format_chunks`：验证输出包含 `[CHUNK start=` 标记
- **验证**: `uv run pytest tests/test_process.py -v`
- **依赖**: Step 1.1（`SubtitleEntry` 可独立定义在 process.py 中）

---

## Phase 2: 字幕提取（yt-dlp 集成）

### Step 2.1 — `extract.py` 实现

- [ ] **文件**: `src/yt2notion/extract.py`
  - `extract_metadata(url: str) -> VideoMeta`：调 `yt-dlp --dump-json`，解析 JSON
  - `extract_subtitles(url: str, config: dict, output_dir: Path) -> Path`：
    - 按优先级尝试下载字幕：zh-Hans → zh-Hant → en (manual) → en (auto)
    - 返回下载到的字幕文件路径
    - 支持 `--cookies-from-browser` 参数
  - `class ExtractionError(Exception)` 自定义异常
  - 内部 helper `_run_ytdlp(args: list[str]) -> subprocess.CompletedProcess`：封装子进程调用
- [ ] **新建**: `tests/test_extract.py`
  - `test_extract_metadata_parsing`：mock `subprocess.run`，传入 yt-dlp JSON 输出，验证 `VideoMeta` 字段
  - `test_subtitle_priority`：mock yt-dlp，模拟有 zh-Hans + en 字幕时选 zh-Hans
  - `test_subtitle_fallback_to_auto`：无 manual 字幕时 fallback 到 auto
  - `test_extraction_error`：yt-dlp 返回非零码时抛 `ExtractionError`
  - `test_cookies_flag`：验证 config 中 `cookies_from` 传入了正确参数
- **验证**: `uv run pytest tests/test_extract.py -v`（全 mock，不需要网络）
- **依赖**: Step 1.1（`VideoMeta`）

---

## Phase 3: LLM 后端

### Step 3.1 — Prompt 模板加载

- [ ] **新建**: `src/yt2notion/prompts/__init__.py`
  - `load_prompt(name: str) -> str`：读取 `prompts/{name}.md`
  - `render_prompt(name: str, **kwargs) -> str`：简单 `str.format()` 替换
- [ ] **测试**: `tests/test_prompts.py`
  - `test_load_summarize_prompt`：确认加载不报错，包含 "timestamp"
  - `test_load_chinese_prompt`：确认包含 "中文"
  - `test_render_prompt`：带变量替换
- **验证**: `uv run pytest tests/test_prompts.py -v`
- **依赖**: 无

### Step 3.2 — Claude Code 后端 (`claude -p`)

- [ ] **文件**: `src/yt2notion/models/claude_code.py`
  - `class ClaudeCodeModel`：
    - `__init__(summarize_model="sonnet", translate_model="opus")`
    - `summarize(transcript: str, metadata: VideoMeta) -> Summary`
    - `to_chinese(summary: Summary, metadata: VideoMeta) -> ChineseContent`
    - 内部调用 `claude -p --model {model} --max-turns 1 --output-format json`
    - 解析 `{"result": "..."}` 拿到 LLM 文本输出
    - 从 LLM 输出中解析 JSON → `Summary` / 从 markdown → `ChineseContent`
  - `_call_claude(prompt: str, model: str) -> str`：封装 subprocess
  - `_parse_summary_json(text: str) -> Summary`：从 LLM 返回文本提取 JSON
  - `_parse_chinese_markdown(text: str) -> ChineseContent`：解析关键节点 markdown
- [ ] **测试**: `tests/test_claude_code.py`
  - `test_call_claude_args`：mock subprocess，验证命令行参数正确
  - `test_parse_summary_json`：给定有效 JSON 输出 → 正确 `Summary`
  - `test_parse_summary_json_with_markdown_fence`：JSON 被 ` ```json ` 包裹时也能解析
  - `test_parse_chinese_markdown`：给定 markdown → 正确 `ChineseContent`
  - `test_summarize_integration`：mock subprocess，完整流程
  - `test_claude_not_found`：`claude` 不在 PATH 时抛明确错误
- **验证**: `uv run pytest tests/test_claude_code.py -v`
- **依赖**: Step 1.1, Step 3.1

### Step 3.3 — Anthropic API 后端

- [ ] **文件**: `src/yt2notion/models/anthropic_api.py`
  - `class AnthropicAPIModel`：
    - `__init__(api_key: str, summarize_model: str, translate_model: str)`
    - 同 `Summarizer` Protocol 签名
    - 使用 `anthropic` SDK 调用 `messages.create()`
  - 复用 Step 3.2 的解析逻辑（抽到 `models/_parsers.py`）
- [ ] **新建**: `src/yt2notion/models/_parsers.py`
  - `parse_summary_json(text: str) -> Summary`
  - `parse_chinese_markdown(text: str) -> ChineseContent`
- [ ] **测试**: `tests/test_anthropic_api.py`
  - `test_api_call_params`：mock `anthropic.Client`，验证 model 和 prompt 传递
  - `test_api_error_handling`：API 报错时包装为自定义异常
  - `test_reuses_parsers`：确认与 claude_code 后端解析逻辑一致
- **验证**: `uv run pytest tests/test_anthropic_api.py -v`
- **依赖**: Step 3.2（共享解析逻辑）

### Step 3.4 — 后端工厂函数

- [ ] **文件**: `src/yt2notion/models/__init__.py`
  - `create_summarizer(config: dict) -> Summarizer`：根据 `config["model"]["backend"]` 返回对应实例
- [ ] **测试**: `tests/test_model_factory.py`
  - `test_create_claude_code` / `test_create_anthropic` / `test_unknown_backend_raises`
- **验证**: `uv run pytest tests/test_model_factory.py -v`
- **依赖**: Step 3.2, Step 3.3

---

## Phase 4: 存储后端

### Step 4.1 — Notion 存储 (`storage/notion.py`)

- [ ] **文件**: `src/yt2notion/storage/notion.py`
  - `class NotionStorage`：
    - `__init__(token, database_id, directory_rules, credit_format)`
    - `save(content, metadata) -> str`：返回创建的 Notion page URL
    - `_build_page_properties(content, metadata) -> dict`：标题、标签、日期
    - `_build_blocks(content, metadata) -> list[dict]`：Notion block 列表
    - `_make_credit_block(metadata) -> dict`：来源信息 callout block
    - `_route_directory(tags, title) -> str`：根据 `directory_rules` 匹配父目录
    - 处理 Notion 2000 字符 block 限制：长段自动拆分
- [ ] **测试**: `tests/test_notion.py`
  - `test_build_properties`：验证 properties dict 结构
  - `test_build_blocks`：验证生成的 block 列表包含 credit + sections
  - `test_credit_block_content`：确认包含 channel、title、URL
  - `test_directory_routing`：匹配 "muscle" → "健身/训练笔记"
  - `test_directory_routing_default`：无匹配 → "收件箱"
  - `test_long_block_split`：超过 2000 字的段落被正确拆分
  - `test_save_calls_api`：mock `notion_client.Client`，验证 `pages.create()` 调用
- **验证**: `uv run pytest tests/test_notion.py -v`
- **依赖**: Step 1.1

### Step 4.2 — 存储工厂函数

- [ ] **文件**: `src/yt2notion/storage/__init__.py`
  - `create_storage(config: dict) -> Storage`：根据 `config["storage"]["backend"]` 返回对应实例
- [ ] **测试**: `tests/test_storage_factory.py`
  - `test_create_notion` / `test_create_obsidian_raises` / `test_unknown_backend_raises`
- **验证**: `uv run pytest tests/test_storage_factory.py -v`
- **依赖**: Step 4.1

---

## Phase 5: CLI 管道串联

### Step 5.1 — Pipeline 编排模块

- [ ] **新建**: `src/yt2notion/pipeline.py`
  - `run_pipeline(url: str, config: AppConfig, verbose: bool) -> str`：
    1. `extract_metadata(url)` → `VideoMeta`
    2. `extract_subtitles(url, config)` → subtitle file path
    3. `parse_subtitle_file(path)` → entries
    4. `chunk_by_time(entries)` → chunks
    5. `format_chunks(chunks)` → transcript text
    6. `summarizer.summarize(transcript, meta)` → `Summary`
    7. `summarizer.to_chinese(summary, meta)` → `ChineseContent`
    8. 用户确认步骤（`typer.confirm`）— 不自动发布
    9. `storage.save(content, meta)` → URL
  - 返回最终 URL / 路径
- [ ] **测试**: `tests/test_pipeline.py`
  - `test_pipeline_full_mock`：mock extract + model + storage，验证完整调用链
  - `test_pipeline_confirm_abort`：用户拒绝发布时不调用 `save()`
  - `test_pipeline_extract_error`：提取失败时管道中断并抛异常
  - `test_pipeline_verbose_output`：verbose=True 时调用额外的输出
- **验证**: `uv run pytest tests/test_pipeline.py -v`
- **依赖**: Step 1.2, Step 1.3, Step 2.1, Step 3.4, Step 4.2

### Step 5.2 — CLI 接入

- [ ] **文件**: `src/yt2notion/cli.py`
  - 实现 `process()` 命令体：加载配置 → 调用 `run_pipeline()`
  - 添加 `--dry-run` 选项：只输出中文内容，不发布
  - 添加 `--no-confirm` 选项：跳过确认直接发布（仍需 flag 显式传入）
  - 错误处理：`ExtractionError` / `ConfigError` → 友好的 typer 错误信息
- [ ] **测试**: `tests/test_cli.py`
  - `test_cli_help`：`typer.testing.CliRunner`，验证 `--help` 正常
  - `test_cli_missing_config`：无 config.yaml 时显示错误
  - `test_cli_dry_run`：mock pipeline，验证不调用 storage
  - `test_cli_process_invocation`：验证参数正确传递到 pipeline
- **验证**: `uv run pytest tests/test_cli.py -v`
- **依赖**: Step 5.1

---

## Phase 6: 质量保证

### Step 6.1 — 测试覆盖率与 lint

- [ ] 在 `pyproject.toml` 添加 `[tool.coverage]` 配置，设定最低覆盖率 80%
- [ ] 运行 `uv run pytest --cov=yt2notion --cov-report=term-missing tests/ -v`
- [ ] 补齐覆盖率不足的模块
- [ ] `uv run ruff check src/ tests/` 零警告
- [ ] `uv run ruff format --check src/ tests/` 格式一致
- **依赖**: Phase 1-5 全部完成

### Step 6.2 — 集成测试 fixtures

- [ ] **新建**: `tests/fixtures/` 目录
  - `sample_ytdlp_metadata.json`：真实的 yt-dlp `--dump-json` 输出样本（脱敏）
  - `sample_summary_response.json`：LLM summarize 步骤的模拟返回
  - `sample_chinese_response.md`：LLM to_chinese 步骤的模拟返回
- [ ] **新建**: `tests/test_integration.py`
  - `test_full_pipeline_with_fixtures`：用上述 fixture 文件 mock 所有外部调用，验证完整管道输出
  - 验证最终 `ChineseContent` 包含来源信息（channel、title、URL）
  - 验证时间戳与 fixture 数据一致
- **验证**: `uv run pytest tests/test_integration.py -v`
- **依赖**: Phase 5

---

## Phase 7: 端到端验证（Claude Code 执行）

### Step 7.1 — 本地端到端测试（Markdown 输出）

此步骤验证不依赖 Notion token，使用 `--dry-run` 将结果输出到终端。

- [ ] 准备 `config.yaml`（基于 `config.example.yaml`，backend 设为 `claude_code`）
- [ ] 执行命令：
  ```bash
  uv run yt2notion "https://www.youtube.com/watch?v=<TEST_VIDEO_ID>" --dry-run -v
  ```
- [ ] 验证清单：
  - yt-dlp 成功下载字幕
  - 字幕正确解析为 timestamped chunks
  - `claude -p --model sonnet` 返回有效 JSON 结构
  - `claude -p --model opus` 返回中文 markdown
  - 输出包含来源信息（频道名、视频标题、URL）
  - 时间戳为可点击的 YouTube 链接
  - 标签为中文

### Step 7.2 — Notion 端到端测试

- [ ] 配置 `config.yaml`，填入真实 Notion token 和 database_id
- [ ] 执行命令：
  ```bash
  uv run yt2notion "https://www.youtube.com/watch?v=<TEST_VIDEO_ID>" -v
  ```
- [ ] 验证清单：
  - Notion 页面成功创建
  - 页面标题为中文
  - 页面包含来源 callout（频道名、标题、链接）
  - 各 section 有正确的时间戳链接
  - Tags multi-select 属性已填充
  - 目录路由规则正确匹配（如健身视频 → "健身/训练笔记"）
- [ ] 在 Notion 中打开页面，人工确认格式和内容质量

### Step 7.3 — 异常路径验证

- [ ] 无字幕视频：验证错误信息清晰
- [ ] 无效 URL：验证错误信息清晰
- [ ] 缺少 `claude` CLI：验证错误信息提示安装
- [ ] 无效 Notion token：验证错误信息提示重新配置

---

## 依赖关系总览

```
Phase 1 (模型 + 处理)     Phase 2 (提取)      Phase 3 (LLM)       Phase 4 (存储)
  1.1 models/base ──────────►2.1 extract ──────►3.2 claude_code ──►4.1 notion
  1.2 config                                    3.1 prompts         4.2 factory
  1.3 process                                   3.3 anthropic_api
                                                3.4 factory
                                                    │
                    ┌───────────────────────────────┘
                    ▼
              Phase 5 (管道)
                5.1 pipeline ──► 5.2 cli
                    │
                    ▼
              Phase 6 (质量)
                6.1 coverage + lint
                6.2 integration tests
                    │
                    ▼
              Phase 7 (E2E)
                7.1 dry-run ──► 7.2 notion ──► 7.3 error paths
```

## 建议执行顺序

可并行的步骤用 `|` 分隔：

1. Step 1.1 | Step 1.2
2. Step 1.3 | Step 2.1 | Step 3.1
3. Step 3.2
4. Step 3.3 | Step 3.4 | Step 4.1
5. Step 4.2
6. Step 5.1
7. Step 5.2
8. Step 6.1 | Step 6.2
9. Step 7.1 → 7.2 → 7.3

预计总共需要新建/修改约 20 个文件，新增约 50+ 个测试用例，目标覆盖率 80%+。
