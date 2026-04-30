---
name: notion-publish
description: Publishing content to Notion databases with proper structure and tags
---

# Notion Publishing

## Page 结构

每个视频生成一个 Notion page，包含：

### Properties（Database columns）

- **Title**: 视频标题（中文，如果原标题是英文则翻译）
- **URL**: YouTube 原始链接
- **Channel**: 频道名称
- **Date**: 视频发布日期
- **Tags**: 自动生成的标签（multi-select）
- **Language**: 原始字幕语言
- **Status**: 默认 "待确认"，用户确认后改为 "已发布"

### Page Body（Blocks）

1. 来源信息 callout block（channel、title、url）
2. 概要（2-3 句话的总结）
3. 关键节点列表，每个节点包含：
   - 时间戳链接（可点击跳转到 YouTube 对应时间）
   - 段落标题
   - 内容摘要
4. 分隔线
5. 完整字幕（toggle block，默认折叠）

## Notion API 注意事项

- Block children 每次最多 append 100 个 blocks
- Rich text 每个 block 最多 2000 字符
- 超长内容需要拆分为多个 paragraph blocks
- `notion-client` Python SDK 的 `pages.create()` 和 `blocks.children.append()` 是分开的调用

## Tags 自动生成规则

用 LLM 从总结内容中提取 3-5 个标签，格式为：
- 主题标签（如：髋关节、力量训练、AI agent）
- 内容类型标签（如：教程、讲座、访谈）

## 目录路由

根据 config.yaml 的 `directory_rules`，用关键词匹配决定 parent page。
匹配逻辑：tags + title 中任一命中规则的 match 词即归入对应 parent。
无匹配则归入 `default` 目录。
