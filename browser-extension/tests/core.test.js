const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");

const context = { URL };
context.globalThis = context;
vm.runInNewContext(fs.readFileSync("browser-extension/core.js", "utf8"), context);
const core = context.Yt2NotionSubtitleCore;

assert.equal(core.videoIdFromUrl("https://www.youtube.com/watch?v=abc&list=one"), "abc");
assert.equal(core.videoIdFromUrl("https://youtu.be/xyz"), "xyz");

const pkg = {
  schema_version: 1,
  video: { id: "abc" },
  quality: { passed: true, semantic_issue_count: 0 },
  cues: [
    { id: "one", start_ms: 1000, end_ms: 2000, source_text: "A", translated_text: "甲" },
    { id: "two", start_ms: 2500, end_ms: 3000, source_text: "B", translated_text: "乙" }
  ]
};
assert.equal(core.validatePackage(pkg), pkg);
assert.equal(core.findCue(pkg.cues, 999), null);
assert.equal(core.findCue(pkg.cues, 1000).id, "one");
assert.equal(core.findCue(pkg.cues, 2000), null);
assert.equal(core.findCue(pkg.cues, 2999).id, "two");
assert.throws(() => core.validatePackage({ ...pkg, cues: [pkg.cues[1], pkg.cues[0]] }), /Invalid cue/);
assert.throws(
  () => core.validatePackage({ ...pkg, quality: { passed: false, semantic_issue_count: 1 } }),
  /quality issues/
);
assert.throws(
  () => core.validatePackage({ ...pkg, cues: [{ ...pkg.cues[0], translated_text: "  " }] }),
  /Invalid cue/
);

console.log("browser-extension core tests passed");
