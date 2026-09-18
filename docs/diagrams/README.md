# Archify diagrams

本目录只提交可维护的 Archify JSON 源规格。Archify `deliver` 生成的自包含 HTML
会重复嵌入完整 viewer runtime，属于本地预览产物，不进入 Git。

先将 `ARCHIFY_DIR` 指向本机安装的 Archify skill，再验证或生成图表：

```bash
export ARCHIFY_DIR=/path/to/archify

node "$ARCHIFY_DIR/bin/archify.mjs" validate sequence \
  docs/diagrams/bilingual-subtitles-generation.sequence.json \
  --quality showcase --json

node "$ARCHIFY_DIR/bin/archify.mjs" deliver sequence \
  docs/diagrams/bilingual-subtitles-generation.sequence.json \
  docs/diagrams/bilingual-subtitles-generation.sequence.html \
  --quality showcase --json
```

播放图同理，将文件名替换为 `bilingual-subtitles-playback.sequence.*`。需要边改边看时，
可将 `deliver` 换成 `preview`；最终交付前仍应执行一次 `deliver`。
