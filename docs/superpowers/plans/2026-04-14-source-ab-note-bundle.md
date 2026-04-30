# Source/A/B Note Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a formal `source + A导读 + B扩展 + tags` note-bundle mode that writes three linked Obsidian notes from one transcript pipeline run.

**Architecture:** Keep the existing extract/review/entity pipeline intact, add a new summarize artifact (`note_bundle.json`) plus a dedicated `note_bundle.py` orchestrator, and make Obsidian publish a coordinated three-note bundle. Preserve the current single-note summary path behind `output.note_mode = single`, and add a new `output.note_mode = source_ab_bundle` branch for the new behavior.

**Tech Stack:** Python dataclasses/protocols, existing LLM backends (`claude_code` / `anthropic_api` / `codex_cli`), markdown prompt templates, workspace JSON artifacts, Obsidian markdown storage, `pytest`, `ruff`.

---

## File Structure

### New Files

- `src/yt2notion/note_bundle.py`
  - Orchestrates `guide -> longform -> metadata` generation from transcript input.
  - Computes duration-based target lengths.
  - Builds a typed `NoteBundle`.
- `src/yt2notion/prompts/compose_guide.md`
  - Prompt for A note (`导读版`).
- `src/yt2notion/prompts/compose_longform.md`
  - Prompt for B note (`扩展版`).
- `src/yt2notion/prompts/compose_note_metadata.md`
  - Prompt for source title, stable tags, variant tags, source summary, source topics.
- `tests/test_note_bundle.py`
  - Unit tests for target sizing, orchestration behavior, and bundle assembly.

### Modified Files

- `src/yt2notion/config.py`
  - Add and validate `output.note_mode`.
- `src/yt2notion/models/base.py`
  - Add typed note-bundle dataclasses and extend `Summarizer` protocol.
- `src/yt2notion/models/_parsers.py`
  - Add parsers for note document JSON and metadata JSON.
- `src/yt2notion/models/claude_code.py`
  - Implement the new note composition methods.
- `src/yt2notion/models/anthropic_api.py`
  - Implement the new note composition methods.
- `src/yt2notion/models/codex_cli.py`
  - Implement the new note composition methods.
- `src/yt2notion/workspace.py`
  - Add `note_bundle.json` save/load helpers.
- `src/yt2notion/pipeline.py`
  - Add bundle mode summarize branch and publish branch.
- `src/yt2notion/storage/base.py`
  - Extend storage protocol for note-bundle publishing.
- `src/yt2notion/storage/obsidian.py`
  - Write coordinated source/A/B markdown files with frontmatter and links.
- `src/yt2notion/cli.py`
  - Include `note_bundle` in `prepare` JSON output.
- `PROJECT_MAP.md`
  - Document new artifact, config mapping, prompt bindings, and Obsidian output behavior.
- `tests/test_config.py`
  - Validate `output.note_mode`.
- `tests/test_workspace.py`
  - Validate `note_bundle.json` persistence.
- `tests/test_prompts.py`
  - Validate prompt loading for the three new templates.
- `tests/test_pipeline.py`
  - Cover bundle summarize/publish branch and compatibility with single mode.
- `tests/test_obsidian_storage.py`
  - Cover source/A/B file output, frontmatter, links, and naming.

---

### Task 1: Add Config, Models, and Workspace Artifact Support

**Files:**
- Modify: `src/yt2notion/config.py`
- Modify: `src/yt2notion/models/base.py`
- Modify: `src/yt2notion/workspace.py`
- Test: `tests/test_config.py`
- Test: `tests/test_workspace.py`

- [ ] **Step 1: Write the failing config test for `output.note_mode`**

```python
def test_output_note_mode_defaults_to_single(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("model:\n  backend: claude_code\nstorage:\n  backend: markdown\n")

    config = load_config(str(config_path))

    assert config.output["note_mode"] == "single"


def test_output_note_mode_rejects_unknown_value(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "model:\n  backend: claude_code\n"
        "storage:\n  backend: markdown\n"
        "output:\n  note_mode: invalid\n"
    )

    with pytest.raises(ConfigError, match="output.note_mode"):
        load_config(str(config_path))
```

- [ ] **Step 2: Run the config tests to verify they fail**

Run: `uv run pytest tests/test_config.py -q`

Expected: FAIL because `note_mode` is missing from defaults/validation.

- [ ] **Step 3: Add `note_mode` defaults and validation**

```python
DEFAULTS = {
    "output": {
        "mode": "summary",
        "note_mode": "single",
        "chunk_duration_seconds": 120,
        "target_language": "zh-CN",
        "long_content_threshold_seconds": 1800,
        "max_segment_seconds": 900,
    },
}

output_note_mode = merged.get("output", {}).get("note_mode", "single")
if output_note_mode not in {"single", "source_ab_bundle"}:
    raise ConfigError(
        "output.note_mode must be either 'single' or 'source_ab_bundle'"
    )
```

- [ ] **Step 4: Run the config tests to verify they pass**

Run: `uv run pytest tests/test_config.py -q`

Expected: PASS for the new note-mode cases.

- [ ] **Step 5: Write the failing model/workspace tests for `note_bundle.json`**

```python
def test_workspace_save_and_load_note_bundle(tmp_path):
    ws = Workspace(tmp_path, "video123")
    bundle = NoteBundle(
        source=NoteDocument(title="source", markdown="# source", tags=["法拉利"], variant="source"),
        guide=NoteDocument(title="guide", markdown="# guide", tags=["导读版"], variant="a_guide"),
        longform=NoteDocument(title="long", markdown="# long", tags=["扩展版"], variant="b_longform"),
        stable_tags=["法拉利", "赛车胜利叙事"],
        source_topics=["稀缺机制", "电动化挑战"],
    )

    ws.save_note_bundle(bundle)
    loaded = ws.load_note_bundle()

    assert loaded is not None
    assert loaded.source.title == "source"
    assert loaded.guide.variant == "a_guide"
    assert loaded.longform.tags == ["扩展版"]
```

- [ ] **Step 6: Run the workspace tests to verify they fail**

Run: `uv run pytest tests/test_workspace.py -q`

Expected: FAIL because `NoteBundle` and workspace helpers do not exist yet.

- [ ] **Step 7: Add typed bundle models and workspace persistence**

```python
@dataclass
class NoteDocument:
    title: str
    markdown: str
    tags: list[str]
    variant: str


@dataclass
class NoteBundle:
    source: NoteDocument
    guide: NoteDocument
    longform: NoteDocument
    stable_tags: list[str]
    source_topics: list[str]


def save_note_bundle(self, bundle: NoteBundle) -> None:
    self._write_json("note_bundle.json", asdict(bundle))


def load_note_bundle(self) -> NoteBundle | None:
    data = self._read_json("note_bundle.json")
    if data is None:
        return None
    return NoteBundle(
        source=NoteDocument(**data["source"]),
        guide=NoteDocument(**data["guide"]),
        longform=NoteDocument(**data["longform"]),
        stable_tags=data.get("stable_tags", []),
        source_topics=data.get("source_topics", []),
    )
```

- [ ] **Step 8: Run the config + workspace tests**

Run: `uv run pytest tests/test_config.py tests/test_workspace.py -q`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/yt2notion/config.py src/yt2notion/models/base.py src/yt2notion/workspace.py tests/test_config.py tests/test_workspace.py
git commit -m "feat: add note bundle config and workspace artifact"
```

---

### Task 2: Add Prompt Templates, Parsers, and Backend Methods

**Files:**
- Create: `src/yt2notion/prompts/compose_guide.md`
- Create: `src/yt2notion/prompts/compose_longform.md`
- Create: `src/yt2notion/prompts/compose_note_metadata.md`
- Modify: `src/yt2notion/models/_parsers.py`
- Modify: `src/yt2notion/models/base.py`
- Modify: `src/yt2notion/models/claude_code.py`
- Modify: `src/yt2notion/models/anthropic_api.py`
- Modify: `src/yt2notion/models/codex_cli.py`
- Test: `tests/test_prompts.py`
- Test: `tests/test_note_bundle.py`

- [ ] **Step 1: Write the failing prompt-loading tests**

```python
def test_load_compose_guide_prompt():
    prompt = load_prompt("compose_guide")
    assert "导读版" in prompt


def test_load_compose_longform_prompt():
    prompt = load_prompt("compose_longform")
    assert "扩展成稿版" in prompt


def test_load_compose_note_metadata_prompt():
    prompt = load_prompt("compose_note_metadata")
    assert "stable_tags" in prompt
```

- [ ] **Step 2: Write the failing parser/backend tests**

```python
def test_parse_note_document_json():
    raw = '{"title": "标题", "markdown": "正文", "tags": ["法拉利"], "variant": "a_guide"}'
    doc = parse_note_document_json(raw, expected_variant="a_guide")
    assert doc.title == "标题"
    assert doc.tags == ["法拉利"]


def test_parse_note_metadata_json():
    raw = '''
    {
      "source_title": "Ferrari",
      "stable_tags": ["法拉利"],
      "variant_tags": {"a": ["播客导读"], "b": ["扩展长文"]},
      "source_summary": "简介",
      "source_topics": ["稀缺机制"]
    }
    '''
    meta = parse_note_metadata_json(raw)
    assert meta["source_title"] == "Ferrari"
    assert meta["variant_tags"]["b"] == ["扩展长文"]
```

- [ ] **Step 3: Run prompt/parser tests to verify they fail**

Run: `uv run pytest tests/test_prompts.py tests/test_note_bundle.py -q`

Expected: FAIL because prompts/parsers/methods are not implemented.

- [ ] **Step 4: Add the three prompt templates**

```md
你是一位中文长文编辑。请把 transcript 改写成导读版文章。

输入信息：
- 标题：{title}
- 频道：{channel}
- 时长：{duration}
- 目标字数：{target_chars}

要求：
- 这是导读版，不是提纲
- 输出严格 JSON：
{
  "title": "...",
  "markdown": "...",
  "tags": ["..."],
  "variant": "a_guide"
}
```

```md
你是一位中文长文编辑。请基于 transcript 和导读版骨架，扩写成长文版。

输入信息：
- 标题：{title}
- 频道：{channel}
- 时长：{duration}
- 目标字数：{target_chars}

输出严格 JSON：
{
  "title": "...",
  "markdown": "...",
  "tags": ["..."],
  "variant": "b_longform"
}
```

```md
你是一位中文知识库编辑。请基于 source metadata、导读版、扩展版输出：
{
  "source_title": "...",
  "stable_tags": ["..."],
  "variant_tags": {"a": ["..."], "b": ["..."]},
  "source_summary": "...",
  "source_topics": ["..."]
}
```

- [ ] **Step 5: Add parser helpers**

```python
def parse_note_document_json(text: str, *, expected_variant: str) -> NoteDocument:
    data = _load_json_object(text)
    variant = str(data.get("variant", "")).strip()
    if variant != expected_variant:
        raise ParseError(f"Expected variant {expected_variant!r}, got {variant!r}")
    return NoteDocument(
        title=str(data.get("title", "")).strip(),
        markdown=str(data.get("markdown", "")).strip(),
        tags=[str(tag).strip() for tag in data.get("tags", []) if str(tag).strip()],
        variant=variant,
    )


def parse_note_metadata_json(text: str) -> dict:
    data = _load_json_object(text)
    return {
        "source_title": str(data.get("source_title", "")).strip(),
        "stable_tags": [str(tag).strip() for tag in data.get("stable_tags", []) if str(tag).strip()],
        "variant_tags": data.get("variant_tags", {"a": [], "b": []}),
        "source_summary": str(data.get("source_summary", "")).strip(),
        "source_topics": [str(topic).strip() for topic in data.get("source_topics", []) if str(topic).strip()],
    }
```

- [ ] **Step 6: Extend the `Summarizer` protocol and all backends**

```python
class Summarizer(Protocol):
    def compose_guide_note(
        self,
        transcript: str,
        metadata: VideoMeta,
        *,
        target_chars: int,
    ) -> NoteDocument:
        ...

    def compose_longform_note(
        self,
        transcript: str,
        guide_note: NoteDocument,
        metadata: VideoMeta,
        *,
        target_chars: int,
    ) -> NoteDocument:
        ...

    def compose_note_metadata(
        self,
        guide_note: NoteDocument,
        longform_note: NoteDocument,
        metadata: VideoMeta,
    ) -> dict:
        ...
```

```python
def compose_guide_note(...):
    system_prompt = render_prompt("compose_guide", ...)
    raw = self._translate_caller.call(system_prompt, transcript)
    return parse_note_document_json(raw, expected_variant="a_guide")
```

- [ ] **Step 7: Run prompt and parser/backend tests**

Run: `uv run pytest tests/test_prompts.py tests/test_note_bundle.py -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/yt2notion/prompts/compose_guide.md src/yt2notion/prompts/compose_longform.md src/yt2notion/prompts/compose_note_metadata.md src/yt2notion/models/_parsers.py src/yt2notion/models/base.py src/yt2notion/models/claude_code.py src/yt2notion/models/anthropic_api.py src/yt2notion/models/codex_cli.py tests/test_prompts.py tests/test_note_bundle.py
git commit -m "feat: add note bundle prompts and backend methods"
```

---

### Task 3: Add `note_bundle.py` Orchestration and Pipeline Integration

**Files:**
- Create: `src/yt2notion/note_bundle.py`
- Modify: `src/yt2notion/pipeline.py`
- Modify: `src/yt2notion/cli.py`
- Test: `tests/test_note_bundle.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing note-bundle orchestration tests**

```python
def test_resolve_note_targets_scales_with_duration():
    guide_chars, longform_chars = resolve_note_targets(duration_seconds=4 * 3600)
    assert 2500 <= guide_chars <= 4000
    assert 7000 <= longform_chars <= 9000


def test_build_note_bundle_calls_guide_then_longform_then_metadata():
    summarizer = FakeSummarizer()
    bundle = build_note_bundle(reviewed_segments, metadata, summarizer)

    assert summarizer.calls == ["guide", "longform", "metadata"]
    assert bundle.source.title == "Ferrari"
    assert bundle.guide.variant == "a_guide"
    assert bundle.longform.variant == "b_longform"
```

- [ ] **Step 2: Run the note-bundle tests to verify they fail**

Run: `uv run pytest tests/test_note_bundle.py -q`

Expected: FAIL because `note_bundle.py` does not exist.

- [ ] **Step 3: Create `note_bundle.py` with sizing + orchestration helpers**

```python
def resolve_note_targets(duration_seconds: int) -> tuple[int, int]:
    hours = max(1.0, duration_seconds / 3600.0)
    guide_chars = max(2000, min(4000, int(round(hours * 2000))))
    longform_chars = max(4000, min(12000, int(round(hours * 2000 * 4))))
    return guide_chars, longform_chars


def build_note_bundle(
    reviewed: list[dict],
    metadata: VideoMeta,
    summarizer: Summarizer,
) -> NoteBundle:
    transcript = format_note_bundle_transcript(reviewed)
    guide_chars, longform_chars = resolve_note_targets(metadata.duration_seconds)
    guide = summarizer.compose_guide_note(transcript, metadata, target_chars=guide_chars)
    longform = summarizer.compose_longform_note(
        transcript,
        guide,
        metadata,
        target_chars=longform_chars,
    )
    meta = summarizer.compose_note_metadata(guide, longform, metadata)
    source = build_source_note(meta, metadata)
    return NoteBundle(
        source=source,
        guide=guide,
        longform=longform,
        stable_tags=meta["stable_tags"],
        source_topics=meta["source_topics"],
    )
```

- [ ] **Step 4: Write the failing pipeline tests for `output.note_mode = source_ab_bundle`**

```python
def test_step_summarize_returns_note_bundle_in_bundle_mode(...):
    config = {"output": {"note_mode": "source_ab_bundle", "long_content_threshold_seconds": 1800}}
    prepared = prepare_content(url, app_config, ...)
    assert prepared.note_bundle is not None
    assert prepared.note_bundle.source.variant == "source"


def test_prepare_json_payload_includes_note_bundle(...):
    result = runner.invoke(app, ["prepare", url, "--config", str(config_path)])
    payload = json.loads(result.stdout)
    assert "note_bundle" in payload
```

- [ ] **Step 5: Run the pipeline/CLI tests to verify they fail**

Run: `uv run pytest tests/test_pipeline.py tests/test_note_bundle.py -q`

Expected: FAIL because pipeline/CLI do not know `note_bundle`.

- [ ] **Step 6: Wire `PreparedContent` and summarize branch**

```python
@dataclass
class PreparedContent:
    metadata: VideoMeta
    chinese_content: ChineseContent | None
    note_bundle: NoteBundle | None
    transcript_segments: list[dict] | None
    entities: EntityResult | None
    workspace: Workspace
    is_long: bool
    output_mode: str
```

```python
def _step_summarize(...):
    note_mode = config.get("output", {}).get("note_mode", "single")
    if note_mode == "source_ab_bundle":
        return build_note_bundle(reviewed, metadata, summarizer)
    ...
```

```python
payload = {
    "mode": prepared.output_mode,
    "note_mode": config.output.get("note_mode", "single"),
    "summary": ... if prepared.chinese_content else None,
    "note_bundle": asdict(prepared.note_bundle) if prepared.note_bundle else None,
}
```

- [ ] **Step 7: Persist `note_bundle.json` in the workspace**

```python
if note_mode == "source_ab_bundle":
    ws.save_note_bundle(note_bundle)
else:
    ws.save_summary(chinese_content)
```

- [ ] **Step 8: Run note-bundle + pipeline tests**

Run: `uv run pytest tests/test_note_bundle.py tests/test_pipeline.py -q`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/yt2notion/note_bundle.py src/yt2notion/pipeline.py src/yt2notion/cli.py tests/test_note_bundle.py tests/test_pipeline.py
git commit -m "feat: add note bundle pipeline branch"
```

---

### Task 4: Extend Storage Protocol and Obsidian Publishing

**Files:**
- Modify: `src/yt2notion/storage/base.py`
- Modify: `src/yt2notion/storage/obsidian.py`
- Test: `tests/test_obsidian_storage.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing Obsidian storage test**

```python
def test_save_note_bundle_writes_source_guide_and_longform(tmp_path):
    storage = ObsidianStorage(str(tmp_path))
    metadata = VideoMeta(video_id="123", title="Ferrari", channel="Acquired", url="https://example.com")
    bundle = NoteBundle(
        source=NoteDocument(title="Acquired《Ferrari》", markdown="# source", tags=["法拉利"], variant="source"),
        guide=NoteDocument(title="Ferrari 导读", markdown="# guide", tags=["导读版"], variant="a_guide"),
        longform=NoteDocument(title="Ferrari 扩展", markdown="# long", tags=["扩展版"], variant="b_longform"),
        stable_tags=["法拉利"],
        source_topics=["稀缺机制"],
    )

    result = storage.save_note_bundle(bundle, metadata)

    assert Path(result).name.endswith("Ferrari.md")
    assert (tmp_path / "yt2notion/summaries/2026-04-14 Ferrari - 导读.md").exists()
    assert (tmp_path / "yt2notion/summaries/2026-04-14 Ferrari - 扩展.md").exists()
```

- [ ] **Step 2: Run the Obsidian storage tests to verify they fail**

Run: `uv run pytest tests/test_obsidian_storage.py -q`

Expected: FAIL because the storage protocol and implementation do not support bundles.

- [ ] **Step 3: Extend the storage protocol**

```python
class Storage(Protocol):
    def save_note_bundle(
        self,
        bundle: NoteBundle,
        metadata: VideoMeta,
        *,
        transcript_segments: list[dict] | None = None,
        entities: EntityResult | None = None,
    ) -> str:
        ...
```

- [ ] **Step 4: Add coordinated Obsidian path resolution and renderers**

```python
def _resolve_bundle_paths(self, metadata: VideoMeta) -> tuple[Path, Path, Path]:
    today = date.today().isoformat()
    sanitized = _sanitize_title(metadata.title)
    summaries_path = self.vault_path / self.summaries_dir
    summaries_path.mkdir(parents=True, exist_ok=True)

    source_file = summaries_path / f"{today} {sanitized}.md"
    source_file = _resolve_unique_path(source_file)
    stem = source_file.stem
    if stem.endswith(f" {sanitized}"):
        prefix = stem[: -(len(sanitized) + 1)]
    else:
        prefix = stem
    guide_file = summaries_path / f"{prefix} {sanitized} - 导读.md"
    longform_file = summaries_path / f"{prefix} {sanitized} - 扩展.md"
    return source_file, guide_file, longform_file
```

```python
def save_note_bundle(self, bundle: NoteBundle, metadata: VideoMeta, **kwargs) -> str:
    source_file, guide_file, longform_file = self._resolve_bundle_paths(metadata)
    source_file.write_text(self._render_note_document(bundle.source, metadata, source_stem=source_file.stem), encoding="utf-8")
    guide_file.write_text(self._render_note_document(bundle.guide, metadata, source_stem=source_file.stem), encoding="utf-8")
    longform_file.write_text(self._render_note_document(bundle.longform, metadata, source_stem=source_file.stem), encoding="utf-8")
    return str(source_file)
```

- [ ] **Step 5: Update pipeline publish branch**

```python
if prepared.note_bundle is not None:
    if config.storage["backend"] != "obsidian":
        raise ValueError("output.note_mode=source_ab_bundle currently requires storage.backend=obsidian")
    result_url = storage.save_note_bundle(
        prepared.note_bundle,
        prepared.metadata,
        transcript_segments=prepared.transcript_segments,
        entities=prepared.entities,
    )
else:
    result_url = storage.save(...)
```

- [ ] **Step 6: Run the storage and pipeline tests**

Run: `uv run pytest tests/test_obsidian_storage.py tests/test_pipeline.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/yt2notion/storage/base.py src/yt2notion/storage/obsidian.py src/yt2notion/pipeline.py tests/test_obsidian_storage.py tests/test_pipeline.py
git commit -m "feat: publish source-ab note bundles to obsidian"
```

---

### Task 5: Update Docs, Prompt Bindings, and End-to-End Verification

**Files:**
- Modify: `PROJECT_MAP.md`
- Modify: `handoff.md`
- Test: `tests/test_prompts.py`
- Test: targeted end-to-end commands

- [ ] **Step 1: Write the failing prompt-binding/doc checks**

```python
def test_project_map_mentions_note_bundle_artifact():
    text = Path("PROJECT_MAP.md").read_text(encoding="utf-8")
    assert "note_bundle.json" in text
    assert "compose_guide.md" in text
    assert "compose_longform.md" in text
    assert "compose_note_metadata.md" in text
```

- [ ] **Step 2: Run the prompt-binding/doc tests to verify they fail**

Run: `uv run pytest tests/test_prompts.py -q`

Expected: FAIL until docs/tests are updated.

- [ ] **Step 3: Update canonical docs**

```md
| `SUMMARIZE` | `pipeline._step_summarize()` | reviewed transcripts | `summary.json` or `note_bundle.json` | controlled by `output.note_mode` |

| `compose_guide.md` | `note_bundle.py` | guide note composition | `{title}`, `{channel}`, `{duration}`, `{target_chars}` |
| `compose_longform.md` | `note_bundle.py` | longform note composition | `{title}`, `{channel}`, `{duration}`, `{target_chars}` |
| `compose_note_metadata.md` | `note_bundle.py` | source/tags metadata | metadata + guide/longform notes |
```

- [ ] **Step 4: Run the targeted full verification suite**

Run:

```bash
uv run pytest tests/test_config.py tests/test_workspace.py tests/test_note_bundle.py tests/test_prompts.py tests/test_pipeline.py tests/test_obsidian_storage.py -q
```

Expected: PASS.

- [ ] **Step 5: Run lint on all touched files**

Run:

```bash
uv run ruff check src/yt2notion/config.py src/yt2notion/models/base.py src/yt2notion/models/_parsers.py src/yt2notion/models/claude_code.py src/yt2notion/models/anthropic_api.py src/yt2notion/models/codex_cli.py src/yt2notion/note_bundle.py src/yt2notion/workspace.py src/yt2notion/pipeline.py src/yt2notion/storage/base.py src/yt2notion/storage/obsidian.py src/yt2notion/cli.py tests/test_config.py tests/test_workspace.py tests/test_note_bundle.py tests/test_prompts.py tests/test_pipeline.py tests/test_obsidian_storage.py
```

Expected: PASS with zero errors.

- [ ] **Step 6: Run one end-to-end Obsidian bundle smoke test**

Run:

```bash
uv run yt2notion prepare "https://podcasts.apple.com/us/podcast/ferrari/id1050462261?i=1000761027849" --config /Users/yangtian/.yt2notion-agent/config.yaml
```

Then publish in bundle mode with an Obsidian-backed config and confirm:

```bash
ls "/Users/yangtian/Library/Mobile Documents/iCloud~md~obsidian/Documents/obsidian/yt2notion/summaries/" | rg "Ferrari"
```

Expected: exactly one source note plus one guide note plus one longform note.

- [ ] **Step 7: Commit**

```bash
git add PROJECT_MAP.md handoff.md tests/test_prompts.py
git commit -m "docs: document source-ab note bundle mode"
```

---

## Self-Review

### Spec coverage

- New persisted artifact: covered in Task 1.
- New prompts/backends: covered in Task 2.
- Summarize pipeline branch and CLI payload: covered in Task 3.
- Obsidian source/A/B writing: covered in Task 4.
- Canonical docs and regression verification: covered in Task 5.

### Placeholder scan

- No `TODO` / `TBD` placeholders remain.
- Every task lists exact files and commands.
- Each new code surface has at least one concrete test snippet.

### Type consistency

- `NoteDocument` and `NoteBundle` are the only new public data models.
- `output.note_mode` uses exactly `single | source_ab_bundle` throughout the plan.
- Bundle variants use exactly `source`, `a_guide`, and `b_longform`.

---

## Execution Notes

- Preserve existing single-note behavior as the default. Do not silently replace it.
- Keep the new mode Obsidian-only in the first implementation. Fail explicitly for other storage backends.
- Do not move source/A/B formatting into prompts alone. Storage remains responsible for frontmatter and filename conventions.
- Do not re-use the experimental prompt filenames as the production entrypoint. The new mode should use dedicated production prompts.
