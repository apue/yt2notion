# Archify diagrams

本目录只提交可维护的 Archify JSON 源规格。Archify renderer 生成的自包含 HTML
会重复嵌入完整 viewer runtime，属于本地预览产物，不进入 Git。

## 当前项目架构

[当前项目架构图源规格](current-architecture.architecture.json) 对照
[`PROJECT_MAP.md`](../../PROJECT_MAP.md) 展示 CLI、四条产品流、共享能力和外部边界。
图中产品流到共享能力的连线表示代表性依赖，不表示每条流只调用其下方的一个组件；
详细步骤与分支以 `PROJECT_MAP.md` 为准。`prepare`、`translation-experiment`、
`subtitle-pack`、`transcribe` 只产出本地 artifact，只有显式 `process` 可经
`Storage` 写入 Obsidian；`process --dry-run` 也不会发布。

先将 `ARCHIFY_DIR` 指向本机安装的 Archify skill，再生成架构图预览：

```bash
export ARCHIFY_DIR=/path/to/archify

node "$ARCHIFY_DIR/renderers/architecture/render-architecture.mjs" \
  docs/diagrams/current-architecture.architecture.json \
  docs/diagrams/current-architecture.architecture.html

node "$ARCHIFY_DIR/scripts/check-render-output.mjs" \
  docs/diagrams/current-architecture.architecture.html
```

## 双语字幕时序图

现有源规格：[生成流程](bilingual-subtitles-generation.sequence.json)、
[插件播放](bilingual-subtitles-playback.sequence.json)。
