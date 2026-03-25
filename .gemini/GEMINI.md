# yt2notion - Gemini CLI 领域知识与配置

这是将媒体内容（YouTube 视频、Podcast 等）提取字幕或进行转写、使用大模型总结，并最终发布到 Notion 的 CLI 管道工具。

## 工作流与开发原则 (Working Style)
1. **先讨论，再动手**：收到新任务或功能需求时，先说明理解并列出方案和 tradeoff。确认方向后再改代码，涉及架构变更需先画清楚影响范围。
2. **遵守底线 (Important)**：
   - 任何内容输出中必须包含原作者信息（频道名称、标题、URL）。
   - **绝对不要**在没有用户确认步骤的情况下自动发布到 Notion（NEVER auto-publish without user confirmation step）。
   - `prompts/` 目录下的 `.md` 文件是 Prompt Template（提示词模板），不是普通文档，禁止随意修改其格式。
   - 性能敏感的改动（特别是 ASR 管道）需要有 Benchmark 数据支持，不要凭感觉优化。

## 技术栈与代码规范 (Tech Stack & Code Style)
- **语言**：Python 3.11+
- **包管理**：`uv`。常用命令：
  - 安装依赖：`uv sync`
  - 运行 CLI：`uv run yt2notion "URL"`
  - 代码规范检查与格式化：`uv run ruff check src/`, `uv run ruff format src/`
  - 运行测试：`uv run pytest tests/ -v`
- **代码风格**：
  - **类型标注**：所有公开函数必须有严格的 Type hints。
  - **接口抽象**：使用 `typing.Protocol` 做接口抽象，不使用 `abc.ABC`。
  - **异常处理**：错误处理使用自定义异常类，定义在各模块内部。
  - **测试**：使用 `pytest`，公用 Fixture 放在 `tests/conftest.py` 中。

## 架构与核心逻辑 (Architecture)
系统采用基于 Protocol 的插件架构。主要接口定义在 `models/base.py` (`Summarizer`), `models/llm.py` (`LLMCaller`), `storage/base.py` (`Storage`)。运行时通过 `config.yaml` 动态挂载后端实现。

### 5 步数据驱动管道 (5-Step Metadata-driven Pipeline)
系统决策基于元数据信号而非 URL 模式匹配：
1. **DOWNLOAD**：下载元数据并尝试提取字幕，无字幕则下载音频。
2. **SEGMENT**：生成分段标记。优先级：原有章节信息 > 描述提取 > 强制通过文本内容进行话题分段。
3. **TRANSCRIBE**：转录。包含字幕分配、分段 ASR 或全量 ASR + 句分。如果遇到极长文本，将触发 3.5 **TOPIC SEGMENT** 步骤使用 Haiku 按话题拆分。
4. **REVIEW**：利用 Haiku 校验 ASR 错误。
5. **SUMMARIZE**：使用大语言模型（Map-Reduce，如 Sonnet 负责分段提取，Opus 负责全局中文润色结合），并发布到存储（Notion）。

## 业务领域知识：YouTube 提取与 Notion 发布规则

### 1. yt-dlp 抓取与预处理 (yt-extract)
- **字幕优先级**：手动简体中文 (`zh-Hans`) > 手动繁体中文 (`zh-Hant`) > 手动英文 (`en`) > 自动生成英文 (`--write-auto-subs`)。
- **预处理**：自动字幕有大量重复行，必须去重。字幕被分为一定时长的 chunk，附带准确的时间戳秒数，用于后续生成可跳转的 YouTube 时间戳链接 (`https://youtu.be/{video_id}?t={seconds}`)。

### 2. Notion 发布规则 (notion-publish)
- **页面属性与标签**：页面包含 Title（中文）、URL、Channel、Date、Tags、Language 和 Status（默认 "待确认"）。Tags 由 LLM 自动生成，应为具体的中文词汇（如“力量训练”、“AI Agent”）。
- **目录规则**：Notion Parent 页面基于 `config.yaml` 结合 Tags 和 Title 的匹配词自动决定。
- **页面内容格式 (Notion Markdown)**：
  - 第一行固定为来源 Callout 块，格式如：`<callout icon="📺" color="gray_bg">**来源**：{channel} 「{title}」\n**链接**：[{url}]({url})</callout>`
  - 采用特定的标题结构：`## 概要`、`## 关键节点`、`## 标签`。
  - **关键节点**必须包含时间戳超链接。
- **Notion API 限制**：写入时注意 Block 每次 append 上限为 100 块，单富文本块长度上限为 2000 字符。