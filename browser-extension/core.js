(function initSubtitleCore(global) {
  "use strict";

  function videoIdFromUrl(url) {
    try {
      const parsed = new URL(url);
      if (parsed.hostname === "youtu.be") return parsed.pathname.slice(1) || null;
      return parsed.searchParams.get("v");
    } catch (_error) {
      return null;
    }
  }

  function validatePackage(payload) {
    if (!payload || payload.schema_version !== 1 || !payload.video || !payload.video.id) {
      throw new Error("This is not a yt2notion subtitle package (schema v1).");
    }
    if (!Array.isArray(payload.cues) || payload.cues.length === 0) {
      throw new Error("The subtitle package has no cues.");
    }
    if (!payload.quality || payload.quality.passed !== true) {
      throw new Error("The subtitle package has unresolved semantic quality issues.");
    }
    let previousStart = -1;
    const ids = new Set();
    for (const cue of payload.cues) {
      if (
        typeof cue.id !== "string" ||
        ids.has(cue.id) ||
        !Number.isFinite(cue.start_ms) ||
        !Number.isFinite(cue.end_ms) ||
        cue.start_ms < previousStart ||
        cue.end_ms <= cue.start_ms ||
        typeof cue.source_text !== "string" ||
        !cue.source_text.trim() ||
        typeof cue.translated_text !== "string" ||
        !cue.translated_text.trim()
      ) {
        throw new Error(`Invalid cue contract near ${cue && cue.id ? cue.id : "unknown cue"}.`);
      }
      ids.add(cue.id);
      previousStart = cue.start_ms;
    }
    return payload;
  }

  function findCue(cues, timeMs) {
    let low = 0;
    let high = cues.length - 1;
    while (low <= high) {
      const middle = (low + high) >> 1;
      const cue = cues[middle];
      if (timeMs < cue.start_ms) high = middle - 1;
      else if (timeMs >= cue.end_ms) low = middle + 1;
      else return cue;
    }
    return null;
  }

  global.Yt2NotionSubtitleCore = { videoIdFromUrl, validatePackage, findCue };
})(typeof globalThis !== "undefined" ? globalThis : window);
