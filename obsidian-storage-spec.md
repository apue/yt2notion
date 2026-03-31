# yt2notion: Obsidian Storage Backend 需求文档

## 背景

当前 yt2notion 仅支持 Notion 作为 storage backend。本需求为项目新增 Obsidian 存储后端，让管道输出直接写入 Obsidian vault 目录，生成带 frontmatter 元数据的 markdown 文件。

核心设计理念：**从文本反推媒体溯源**——用户在 summary 中读到任何要点，都能通过时间戳链接跳转到原始媒体的对应位置；需要更多上下文时，通过 wikilink 跳转到完整 transcript。

## 范围

- 实现 `Storage` Protocol 的 Obsidian backend
- 修改 config 体系支持 Obsidian 配置
- 更新 CLI / 文档 / 示例配置
- **不改动** pipeline 的 step 1-5（download → summarize），仅在 save 阶段分流

---

## 1. 文件结构设计

每个媒体源生成 **两个** markdown 文件，互相通过 wikilink 关联：

### 1.1 Summary 文件（日常阅读入口）

路径：`{vault_path}/{summaries_dir}/{YYYY-MM-DD} {sanitized_title}.md`

```markdown
---
source_url: "https://youtube.com/watch?v=xxx"
channel: "3Blue1Brown"
title: "But what is a GPT?"
media_type: youtube
duration: "26:14"
date_published: 2024-03-15
date_processed: 2026-03-30
tags:
  - AI
  - 数学
transcript: "[[T-2026-03-30 But what is a GPT]]"
---

# But what is a GPT?

> **3Blue1Brown** · 26:14 · [原始视频](https://youtube.com/watch?v=xxx)

## 概述

（来自 ChineseContent.overview）

## 要点

- [05:30](https://youtube.com/watch?v=xxx&t=330) **Embedding 的几何含义**：把词映射到高维空间……
- [12:45](https://youtube.com/watch?v=xxx&t=765) **Attention 的本质**：不是"注意力"，而是信息路由……

## 标签

#AI #数学
```

### 1.2 Transcript 文件（溯源用）

路径：`{vault_path}/{transcripts_dir}/T-{YYYY-MM-DD} {sanitized_title}.md`

```markdown
---
parent: "[[2026-03-30 But what is a GPT]]"
source_url: "https://youtube.com/watch?v=xxx"
type: transcript
---

# Transcript: But what is a GPT?

## Embedding 的几何含义 (05:30-12:44)

[05:30](https://youtube.com/watch?v=xxx&t=330)

逐段校对后的原文……

## Attention 的本质 (12:45-20:00)

[12:45](https://youtube.com/watch?v=xxx&t=765)

逐段校对后的原文……
```

### 1.3 Vault 目录结构

```
{vault_path}/
  {summaries_dir}/        ← 默认 "yt2notion/summaries"
  {transcripts_dir}/      ← 默认 "yt2notion/transcripts"
```

不按 channel 或主题建子文件夹。分类通过 frontmatter 属性 + Dataview 查询实现。

### 1.4 文件命名规则

- Summary: `{YYYY-MM-DD} {sanitized_title}.md`
- Transcript: `T-{YYYY-MM-DD} {sanitized_title}.md`
- `sanitized_title`：取 `VideoMeta.title`，去掉文件系统不允许的字符（`/ \ : * ? " < > |`），截断至合理长度（建议 100 字符），保留中文
- `YYYY-MM-DD`：取 `date_processed`（即运行日期），不是视频发布日期（因为发布日期可能缺失）
- 如遇同名文件，追加 `-2`, `-3` 后缀

---

## 2. Frontmatter 字段规范

### Summary frontmatter

| 字段 | 类型 | 来源 | 必填 | 说明 |
|------|------|------|------|------|
| `source_url` | string | `VideoMeta.url` | 是 | 原始媒体 URL |
| `channel` | string | `VideoMeta.channel` | 是 | 频道/播客名 |
| `title` | string | `VideoMeta.title` | 是 | 原始标题 |
| `media_type` | string | 推断 | 是 | `youtube` \| `podcast` |
| `duration` | string | `VideoMeta.duration` | 是 | 格式 `HH:MM:SS` 或 `MM:SS` |
| `date_published` | date | `VideoMeta.upload_date` | 否 | 可能缺失，缺失时省略 |
| `date_processed` | date | 运行时生成 | 是 | pipeline 执行日期 |
| `tags` | list[string] | `ChineseContent.tags` | 是 | LLM 生成的标签 |
| `transcript` | string | 生成 | 是 | wikilink 指向 transcript 文件 |

### Transcript frontmatter

| 字段 | 类型 | 来源 | 必填 | 说明 |
|------|------|------|------|------|
| `parent` | string | 生成 | 是 | wikilink 指向 summary 文件 |
| `source_url` | string | `VideoMeta.url` | 是 | 原始媒体 URL |
| `type` | string | 固定值 | 是 | 始终为 `"transcript"` |

---

## 3. Markdown 渲染规则

### 3.1 时间戳链接

所有时间戳渲染为可点击的 URL，格式为：

- YouTube: `[MM:SS](https://youtube.com/watch?v={id}&t={seconds})`
- Podcast: `[MM:SS]`（无链接，podcast 通常无深度链接）

时间戳数据来自 `ChineseContent.key_points[].timestamp`，已在 pipeline step 5 之前绑定到 chunk，不需要 Obsidian storage 层做额外计算。

### 3.2 要点格式

```markdown
- [05:30](url&t=330) **要点标题**：要点摘要内容……
```

每个 key_point 渲染为一个列表项，时间戳 + 加粗标题 + 摘要。

### 3.3 Transcript 段落格式

每个 reviewed transcript segment 渲染为一个二级标题 + 时间戳 + 正文：

```markdown
## {segment_title} ({start_time}-{end_time})

[{start_time}](url&t={seconds})

{reviewed_text}
```

### 3.4 Source credit

Summary 文件开头必须包含 source credit 行（与现有 CLAUDE.md 约束一致）：

```markdown
> **{channel}** · {duration} · [原始视频]({source_url})
```

---

## 4. 配置变更

### 4.1 config.yaml 新增 obsidian section

```yaml
storage:
  backend: obsidian           # "notion" | "obsidian"

  obsidian:
    vault_path: "/Users/yang/Documents/MyVault"   # 必填，Obsidian vault 根目录
    summaries_dir: "yt2notion/summaries"           # 可选，默认值如左
    transcripts_dir: "yt2notion/transcripts"       # 可选，默认值如左
```

### 4.2 config.py 变更

- `VALID_STORAGE_BACKENDS` 确认包含 `"obsidian"`（可能已有）
- `AppConfig` dataclass 新增 obsidian 相关字段，或在 `storage` 子配置中新增
- `vault_path` 在 backend 为 obsidian 时必填，需校验：
  - 路径存在且是目录
  - 路径可写
  - 如 summaries_dir / transcripts_dir 子目录不存在，自动创建

### 4.3 config.example.yaml 变更

在现有 `storage` section 下，保留 notion 配置（注释掉），新增 obsidian 配置（注释掉），并加注释说明二选一：

```yaml
storage:
  # Choose one backend: "notion" or "obsidian"
  backend: notion

  # --- Notion ---
  notion:
    token: "ntn_xxx"
    database_id: "xxx"
    # ...existing fields...

  # --- Obsidian ---
  # obsidian:
  #   vault_path: "/path/to/your/vault"
  #   summaries_dir: "yt2notion/summaries"       # optional
  #   transcripts_dir: "yt2notion/transcripts"   # optional
```

---

## 5. 代码变更清单

### 5.1 新增文件

| 文件 | 说明 |
|------|------|
| `src/yt2notion/storage/obsidian.py` | `ObsidianStorage` 类，实现 `Storage` Protocol |
| `tests/test_obsidian_storage.py` | 单元测试 |

### 5.2 修改文件

| 文件 | 变更 |
|------|------|
| `src/yt2notion/storage/__init__.py` | `create_storage()` 工厂函数中，`obsidian` 分支从 stub 改为实际导入 `ObsidianStorage` |
| `src/yt2notion/config.py` | 新增 obsidian 配置字段、校验逻辑 |
| `config.example.yaml` | 新增 obsidian section |
| `README.md` | Storage Backends 表格中 obsidian 状态从 🚧 改为 ✅，Quick Start 中补充 obsidian 用法 |
| `CLAUDE.md` | Architecture section 更新 Storage 实现列表 |
| `PROJECT_MAP.md` | Config ↔ Code 映射表、Factory Functions 表、扩展 checklist 更新 |

### 5.3 不需要修改的文件

- `pipeline.py`：不动，它调用 `storage.save()` 接口，不关心实现
- `models/` 目录下所有文件：不动
- `prompts/` 目录下所有文件：不动
- `cli.py`：不动（除非要加 `--vault-path` CLI 覆盖参数，见下方可选项）

---

## 6. ObsidianStorage 实现要点

### 6.1 Protocol 接口

```python
class Storage(Protocol):
    def save(self, meta: VideoMeta, content: ChineseContent, transcript_segments: list) -> str:
        """保存内容，返回保存位置的标识（Notion 返回 page URL，Obsidian 返回文件路径）"""
        ...
```

需确认现有 `Storage` protocol 的 `save()` 签名，确保 `ObsidianStorage.save()` 接收到足够信息来生成两个文件。特别注意：

- `VideoMeta` 提供 metadata（url, channel, title, duration, upload_date）
- `ChineseContent` 提供 summary 内容（overview, key_points, tags, raw_markdown）
- `transcript_segments` 提供校对后的逐段原文

如果现有签名缺少 `transcript_segments` 参数，需要扩展 Protocol 和 NotionStorage 实现（NotionStorage 已经在 save 时创建 transcript 子页面，应该已经有这个数据）。

### 6.2 核心逻辑

```
save(meta, content, transcript_segments):
    1. sanitize title → 生成文件名
    2. 确保 summaries_dir 和 transcripts_dir 存在（os.makedirs）
    3. 渲染 summary markdown（frontmatter + body）
    4. 渲染 transcript markdown（frontmatter + body）
    5. 处理文件名冲突（追加 -2, -3 等）
    6. 写入两个文件（UTF-8 编码）
    7. 返回 summary 文件的绝对路径
```

### 6.3 YAML frontmatter 序列化

使用标准库或简单字符串拼接生成 YAML frontmatter。不引入 PyYAML 作为必需依赖（Obsidian backend 应该零额外依赖，只用标准库）。如果项目已有 PyYAML（通过其他路径），可以用，否则手动拼接即可——frontmatter 结构简单且固定。

---

## 7. 测试要求

### 7.1 单元测试

- 文件名 sanitize：特殊字符、超长标题、中文标题、空标题
- Frontmatter 生成：字段完整性、YAML 合法性、wikilink 格式正确
- Markdown 渲染：时间戳链接格式、YouTube vs podcast 区别
- 文件写入：正确路径、UTF-8 编码、目录自动创建
- 文件名冲突处理：同名文件追加后缀
- Config 校验：vault_path 不存在时报错、vault_path 不可写时报错

### 7.2 集成测试（可选）

- 用 tmpdir 模拟 vault，跑完整 save()，验证两个文件内容和互相链接的正确性

---

## 8. 可选增强（本次不实现，记录备用）

- **CLI `--vault-path` 覆盖**：`uv run yt2notion --vault-path /tmp/test "URL"` 临时覆盖 config 中的 vault_path，方便调试
- **Dataview 仪表盘模板**：首次运行时在 vault 中自动生成一个 `views/Dashboard.md`，包含常用 Dataview 查询
- **`--storage` CLI 参数**：命令行直接切换 backend，无需改 config.yaml
- **Mindmap 渲染**：如果 ChineseContent 包含 mindmap 字段，渲染为 Obsidian 的 mermaid 代码块
- **重复检测**：save 前检查 vault 中是否已有相同 source_url 的文件，给出提示

---

## 9. 验收标准

1. `config.yaml` 设置 `storage.backend: obsidian` + `vault_path` 后，`uv run yt2notion "YouTube URL"` 成功在 vault 中生成两个 .md 文件
2. Summary 文件可在 Obsidian 中正常打开，frontmatter 被识别为属性
3. 时间戳链接可点击跳转到 YouTube 对应时间点
4. Summary 中的 transcript wikilink 可点击跳转到 transcript 文件
5. Transcript 中的 parent wikilink 可点击跳转回 summary 文件
6. Dataview 查询 `FROM "yt2notion/summaries"` 能正确列出所有 summary 及其属性
7. 所有现有测试通过（`uv run pytest tests/ -v`）
8. `uv run ruff check src/` 无新增 warning
9. `storage.backend: notion` 的行为完全不受影响
