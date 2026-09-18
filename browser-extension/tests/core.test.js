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
assert.deepEqual(Array.from(core.findActiveCues(pkg.cues, 999), (cue) => cue.id), []);
assert.deepEqual(Array.from(core.findActiveCues(pkg.cues, 1000), (cue) => cue.id), ["one"]);
assert.deepEqual(Array.from(core.findActiveCues(pkg.cues, 2000), (cue) => cue.id), []);
assert.deepEqual(Array.from(core.findActiveCues(pkg.cues, 2999), (cue) => cue.id), ["two"]);

const overlapping = [
  { id: "A", start_ms: 1000, end_ms: 3000 },
  { id: "B", start_ms: 2000, end_ms: 4000 },
  { id: "C", start_ms: 5000, end_ms: 6000 }
];
assert.deepEqual(Array.from(core.findActiveCues(overlapping, 1999), (cue) => cue.id), ["A"]);
assert.deepEqual(Array.from(core.findActiveCues(overlapping, 2000), (cue) => cue.id), ["A", "B"]);
assert.deepEqual(Array.from(core.findActiveCues(overlapping, 2999), (cue) => cue.id), ["A", "B"]);
assert.deepEqual(Array.from(core.findActiveCues(overlapping, 3000), (cue) => cue.id), ["B"]);
assert.deepEqual(Array.from(core.findActiveCues(overlapping, 4000), (cue) => cue.id), []);
assert.deepEqual(Array.from(core.findActiveCues(overlapping, 4999), (cue) => cue.id), []);
assert.deepEqual(Array.from(core.findActiveCues(overlapping, 5000), (cue) => cue.id), ["C"]);
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
