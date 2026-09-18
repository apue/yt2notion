# yt2notion Bilingual Subtitles extension

## Load it in Chrome

1. Run `uv run yt2notion subtitle-pack "YOUTUBE_URL"` and note the reported
   `package_path`.
2. Open `chrome://extensions`, enable **Developer mode**, choose **Load unpacked**,
   and select this `browser-extension/` directory.
3. Open the matching YouTube video and turn YouTube's own captions off.
4. Click the extension, choose `bilingual_subtitles.json`, and start playback.

Packages are validated and stored locally by YouTube video ID. The extension
does not send subtitle content to a server and does not invoke an LLM. Use the
popup controls to enable the overlay, change text size, or move it vertically.
When source cues overlap, all currently active cues appear in order as a rolling
multiline window; gaps hide the overlay and seeking rebuilds the window from the
target playback time. The overlay follows the actual video element and uses 92%
of its width in standard, theater, and fullscreen layouts.
