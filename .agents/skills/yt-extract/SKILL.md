---
name: yt-extract
description: YouTube subtitle extraction and preprocessing with yt-dlp
---

# YouTube Subtitle Extraction

## yt-dlp 字幕提取

字幕优先级（按顺序尝试，第一个成功的即停）：

1. 手动上传的中文字幕：`--sub-langs "zh-Hans,zh-Hant"`
2. 手动上传的英文字幕：`--sub-langs "en"`
3. 自动生成的英文字幕：`--write-auto-subs --sub-langs "en"`

### 提取命令模式

```bash
# 尝试手动字幕
yt-dlp --cookies-from-browser chrome \
  --write-subs --sub-langs "zh-Hans,zh-Hant,en" \
  --skip-download --convert-subs srt \
  -o "%(id)s" "$URL"

# 如果没有手动字幕，fallback 到自动字幕
yt-dlp --cookies-from-browser chrome \
  --write-auto-subs --sub-langs "en" \
  --skip-download --convert-subs srt \
  -o "%(id)s" "$URL"
```

### 元数据提取

```bash
yt-dlp --cookies-from-browser chrome \
  --print "%(title)s\n%(channel)s\n%(upload_date)s\n%(id)s\n%(duration)s" \
  "$URL"
```

## SRT 预处理规则

1. 解析 SRT/VTT 为 `(start_seconds, text)` 元组列表
2. 合并相邻的重复行（自动字幕常见）
3. 按 `chunk_duration_seconds`（默认 120s）分 chunk
4. 每个 chunk 附带起始时间戳（秒数），用于生成 YouTube 时间戳链接
5. 时间戳链接格式：`https://youtu.be/{video_id}?t={seconds}`

## Gotchas

- 自动字幕会有大量重复行，必须去重
- `--cookies-from-browser chrome` 在 macOS 上需要 Chrome 未被锁定（Keychain 访问）
- 某些视频只有 VTT 没有 SRT，用 `--convert-subs srt` 统一格式
- `upload_date` 格式是 `YYYYMMDD`，需要转换
