# LLM 精校双语字幕设计

状态：MVP 已实现，等待指定视频人工验收

## 目标

输入单个 YouTube URL，生成保留逐条字幕时间轴的双语字幕包。用户关闭
YouTube 原生字幕后，由浏览器插件根据播放器时间显示经过上下文校对和翻译的
原文与简体中文字幕。

第一阶段建立可验证的最小闭环：

1. CLI 预生成双语字幕包；
2. 浏览器插件手动导入字幕包；
3. 插件按 YouTube video ID 匹配，并与播放器同步显示。

## MVP 边界

- 只处理单个 YouTube 视频；URL 中的 playlist 参数不触发批量处理。
- 人工字幕保持源文本不变，直接进入翻译。
- 自动字幕和 ASR 结果先经过上下文校对，再进入翻译。
- 有可用字幕时不为 MVP 额外下载音频；没有字幕时下载音频并进入现有 ASR 路径。
- 音频辅助校对属于后续高质量模式，不阻塞第一阶段闭环。
- 字幕在播放前生成，不做边播放边翻译。
- 插件第一阶段不启动本地服务、不调用 LLM，也不自动操作 YouTube 的 CC 开关。
- 不改变现有笔记生成、translation experiment 或 Obsidian 发布行为。

## 当前项目能力与新增边界

可以直接复用的能力：

- `YtDlpMediaSource` 的 metadata、人工字幕、自动字幕和音频 fallback；
- `SubtitleEntry` 以及 SRT/VTT 的逐条时间戳解析；
- `TranscriptionEngine` 的 ASR、分片、checkpoint 和 fallback；
- `LLMCaller` 及现有模型配置；
- 已验证的中文课程翻译原则和 workspace artifact 机制。

不能直接作为播放契约复用的是 `transcripts.json`。它服务于笔记 pipeline，会把
逐条字幕合并成章节或长 segment，因此缺少浏览器播放所需的 cue 级时间轴。新功能
应在字幕解析后保留 cue，并建立独立的双语字幕 artifact。

## 组件职责

| 组件 | 职责 |
|---|---|
| `SubtitlePackUseCase` | 编排获取、context、校对、翻译、校验和 artifact 写入 |
| `ContextBuilder` | 从当前视频证据和完整字幕构建紧凑的上下文包 |
| `SubtitleReviewer` | 只校对自动字幕和 ASR 文本，不改变 ID 或时间轴 |
| `SubtitleTranslator` | 将校对后的 cue 翻译为简体中文，保持 ID 一一对应 |
| `SubtitleValidator` | 执行确定性结构校验和 LLM 语义质量检查 |
| Browser extension | 导入、存储、匹配视频、同步播放器并显示双语字幕 |

这些名称描述职责，最终实现应优先服从现有模块边界，避免为每项职责创建无必要的
单独抽象。

## 完整生成流程

[打开可交互的双语字幕生成时序图](./diagrams/bilingual-subtitles-generation.sequence.html)

[查看可维护的 Archify JSON 源规格](./diagrams/bilingual-subtitles-generation.sequence.json)

## Context 构建

Context Builder 自动使用：

- 原始 URL 和 video ID；
- title、channel、description 和 chapters；
- 字幕来源类型；
- 完整原始字幕；
- 当前批次的前后 cue；
- LLM 对当前领域的既有知识。

输出由两部分组成：

1. **来源证据**：直接保存 metadata、description 等原始信息；
2. **translation brief**：模型从这些证据与完整字幕中提炼的课程、领域、人物和主题。

translation brief 是帮助分批处理保持全局语境的摘要，不覆盖来源证据。具体人物、
课程编号和罕见专名优先以当前视频 description 等直接证据为准；领域术语由模型结合
内容语境和专业知识处理。

示意结构：

```json
{
  "source_evidence": {
    "title": "AI Agents Course",
    "channel": "CMU",
    "description": "...",
    "chapters": []
  },
  "global_brief": {
    "content_type": "university lecture",
    "domain": "AI agents and NLP",
    "course": "CMU CS 11-768",
    "speakers": ["Daniel Fried", "Graham Neubig"],
    "topics": ["agent architectures", "language models"]
  },
  "section_contexts": ["每个有界字幕窗口的领域、人物、主题与术语证据"]
}
```

## Context 持久化与模型窗口

Context 不能依赖 LLM 会话记忆。当前 `LLMCaller` 是 one-shot 文本接口：Claude CLI
限制为一次 turn，Codex CLI 和 Anthropic API 调用也不会继承上一个字幕批次的会话。
因此 provider 是否支持 context compaction，不属于字幕 pipeline 的正确性前提。

`subtitle_context.json` 是跨批次和断点恢复的 context 真源。每次校对、翻译、语义
检查和定向修复都重新构造一个自包含请求，按以下优先级显式携带信息：

1. 不变的任务与输出契约，包括字幕来源、目标语言和 ID 保持规则；
2. translation brief 中的课程、领域、人物和主题；
3. 当前 cue 批次及其前后文。

这一步是应用层可验证的 **context projection**，不是把不断增长的聊天记录交给模型
自动压缩。完整 evidence 和完整字幕始终留在 workspace；单次请求只投影完成当前任务
所需的有界内容。如果预计输入超过模型窗口，应用应进一步缩小 cue 批次，而不是删除
课程、领域、人物或输出契约。低优先级的宽泛主题摘要可以先被省略。

每个校对、翻译和 QA checkpoint 都记录 `context_fingerprint`。title、description、
translation brief、prompt 或源字幕任一变化时，对应 checkpoint 失效并重新生成，避免
恢复任务时把旧 context 下的结果混入新字幕包。这样即使进程重启、切换 LLM backend，
或者模型内部采用不同的窗口管理策略，关键 context 仍由 artifact 和每次请求显式保留。

## 长内容与超出模型窗口

两小时以上内容不能假设完整字幕适合一次 context 分析、翻译或 QA 调用。pipeline 在
开始 LLM 工作前先按模型预算规划批次；时间长度只用于估算，实际边界由 cue 完整性、
章节边界和保守的输入/输出 token 预算共同决定。任何阶段都不能静默截断字幕。

长内容使用三层上下文：

1. **全局证据**：title、channel、description、series、chapters、字幕来源和输出契约，始终保留；
2. **分段 context**：Context Builder 分批扫描字幕，为每个章节或时间窗口提取主题、人物、
   课程事实和对应 evidence cue IDs；
3. **局部窗口**：当前待处理 cue，加上前后少量只读 cue，只有当前批次 ID 可以出现在输出。

Context Builder 本身采用 map/reduce，而不是先把完整字幕交给一次 LLM 调用：

```text
完整 cue 时间轴
    → 按章节/预算切成 context windows
    → 各窗口生成带 evidence cue IDs 的 SectionContext
    → 合并 metadata 与所有 SectionContext
    → 生成有界的 GlobalBrief + SectionContext 索引
```

如果 SectionContext 索引本身仍超过预算，则按章节树继续分层归并，直到根级 brief
满足固定预算；原始 evidence cue IDs 始终保留在叶节点 artifact 中。

校对和翻译请求携带 `GlobalBrief + 局部窗口`。批次不拆开单个 cue；相邻批次共享
三个只读 overlap cue，但每个 cue 只有一个 owner batch，避免重复输出和时间轴冲突。
叶节点 `SectionContext` 保存在 artifact 中，后续可在不改变字幕包契约的情况下进一步
投影到对应生成批次。

校验也分层执行：

- 每批执行 ID、顺序、覆盖和局部语义校验；
- 每个批次边界检查跨窗口句子和指代是否连贯；
- 每个章节执行语义 QA；
- 全片只对紧凑的 context 索引、章节问题清单和确定性统计做一致性检查，不把两小时
  全文与全文译文再次塞入一个请求；
- 最终 cue 覆盖、时间轴和 artifact schema 仍由程序对完整字幕包一次性校验。

checkpoint identity 至少包含源 cue 范围及哈希、GlobalBrief 指纹、SectionContext 指纹、
模型和 prompt 指纹。中断后只恢复匹配的批次；某个局部窗口变化时可重做受影响窗口，
GlobalBrief 变化则使所有依赖它的校对、翻译和 QA checkpoint 失效。

## Cue 与字幕包契约

每个 cue 的 ID 和时间轴由程序生成，LLM 只能返回与 ID 对应的文本。

```json
{
  "schema_version": 1,
  "video": {
    "id": "UwfjzyLnvMg",
    "title": "...",
    "channel": "...",
    "url": "https://www.youtube.com/watch?v=UwfjzyLnvMg"
  },
  "source_language": "en",
  "target_language": "zh-CN",
  "source_kind": "automatic_caption",
  "context_fingerprint": "sha256:...",
  "quality": {"passed": true, "semantic_issue_count": 0},
  "cues": [
    {
      "id": "cue-000001",
      "start_ms": 1240,
      "end_ms": 4380,
      "original_text": "thank you Graeme",
      "source_text": "Thank you, Graham.",
      "translated_text": "谢谢你，Graham。"
    }
  ]
}
```

人工字幕的 `original_text` 与 `source_text` 相同。自动字幕和 ASR 同时保留两者，以便
检查模型改动。浏览器插件只依赖 `id`、时间轴、`source_text` 和
`translated_text`。

最终契约至少满足：

- cue ID 唯一、稳定且严格有序；
- `start_ms >= 0` 且 `end_ms > start_ms`；
- cue 顺序不能被 LLM 改变；
- 每个源 cue 恰好对应一个校对结果和一个译文；
- 原文与译文不能为空；
- artifact 包含标题、频道和规范化单视频 URL；
- checkpoint identity 包含源字幕、context、模型和 prompt 指纹。

## 校验策略

### 确定性校验

- JSON schema 和字段类型；
- ID 完整性、唯一性和顺序；
- cue 数量与翻译覆盖；
- 时间轴范围和顺序；
- 原文与译文非空。

### LLM 语义校验

- 是否漏译或改变原意；
- 是否错误处理人物、机构、课程和技术术语；
- 是否因 cue 边界造成指代断裂或上下文不连贯；
- 校对是否加入原文不存在的事实。

LLM 语义校验只返回问题列表。修复阶段按问题 cue 定向生成，再重新执行确定性校验；
它不能绕过结构门槛，也不能静默接受未解决的阻塞问题。

## Profiling 与性能分析

现有 `StageTimer` 继续提供 acquire/segment/transcribe 耗时；字幕服务另外记录本地阶段、
逻辑 LLM 调用和 checkpoint 收益。字幕 pipeline 每次运行都写一份结构化 profile；运行成功或
失败都在 `finally` 路径落盘，避免只留下成功样本。

计时分为三层：

1. **运行与阶段**：acquire、parse/normalize、context map、context reduce、review、
   translate、deterministic validation、semantic QA、repair、artifact write 和 total；
2. **批次操作**：batch ID、cue 范围、字符/token 估算、生成或 checkpoint reuse、状态和
   耗时；
3. **provider 重试**：当前 adapter 在 `LLMCaller` 内部封装 retry，MVP profile 只记录包含
   内部 retry 在内的逻辑调用 wall time，不能把它误报成单次 provider attempt。若后续需要
   attempt 级 p95，再在共享 retry 边界增加 observer，而不是改变字幕业务契约。

所有 elapsed time 使用 monotonic clock；UTC 时间只用于标识和跨运行关联。未来允许并行
批次时，`total_seconds` 表示真实 wall time，批次和调用耗时允许重叠，不能简单相加后当作
总耗时。

当前 profile 契约示意：

```json
{
  "schema_version": 1,
  "run_id": "20260918T103000.000000Z",
  "status": "completed",
  "error_type": null,
  "elapsed_seconds": 184.2,
  "stages": [
    {"name": "build_context", "elapsed_seconds": 21.4, "status": "completed"},
    {"name": "generate_batches", "elapsed_seconds": 96.7, "status": "completed"}
  ],
  "llm_calls": [
    {
      "operation": "generate",
      "batch_id": "batch-0007",
      "cue_start": "cue-000241",
      "cue_end": "cue-000278",
      "input_chars": 6840,
      "output_chars": 3210,
      "reused_checkpoint": false,
      "elapsed_seconds": 8.6,
      "status": "completed"
    }
  ]
}
```

Profile 不保存 prompt、字幕正文、API key、环境变量或完整 provider 输出，只保存计数、
稳定 ID、状态、错误类别和耗时。当前 CLI adapter 没有可信 token usage，因此只记录输入
与输出字符数，不伪造精确 token 数据。

每次运行保存在 `profiles/<run-id>.json`，因此 checkpoint rerun 和 fresh run 可以直接
比较。CLI 结果返回本次 profile 路径。后续分析可以计算各 operation 的调用数、
失败率、checkpoint 命中率、p50/p95 latency、每千字符耗时，以及 LLM 时间占总 wall time
的比例。

## Artifact 布局

```text
workspace/<video-id>/
├── metadata.json
├── subtitles.srt                 # 有字幕时的下载结果
├── audio.mp3                     # 无字幕进入 ASR 时才存在
├── subtitle_context.json
├── source_cues.json
├── reviewed_cues.json            # 自动字幕/ASR 时存在
├── bilingual_subtitles.json
├── bilingual_subtitles.srt
├── subtitle_quality_report.json
└── profiles/
    └── <run-id>.json
```

`bilingual_subtitles.json` 是浏览器插件的稳定输入。其他 artifact 服务于来源追踪、
checkpoint、问题诊断和恢复执行。`subtitle_checkpoints/` 保存 context 与合法生成批次；
模型返回的非法批次不会写入 checkpoint。

## 浏览器播放流程

[打开可交互的浏览器字幕播放时序图](./diagrams/bilingual-subtitles-playback.sequence.html)

[查看可维护的 Archify JSON 源规格](./diagrams/bilingual-subtitles-playback.sequence.json)

Overlay 默认挂载在文档根节点；进入浏览器全屏时移入 `document.fullscreenElement`，
因此仍属于全屏 DOM 子树。同步以 `HTMLVideoElement.currentTime` 为唯一时间源，因此
暂停、seek 和倍速不会产生独立计时器漂移。

## 实施顺序

1. 已定义 cue、context、字幕包、质量报告和 profiling 契约与 contract tests；
2. 已实现人工字幕 cue 直读，以及 ASR chunk cue 时间轴恢复；
3. 已实现层级 context map/reduce、人工/自动字幕分支和 checkpoint；
4. 已实现 ID 驱动的校对/翻译、确定性校验、一次定向修复和复检；
5. 已新增 `subtitle-pack` CLI 并生成 JSON/SRT；
6. 已实现 Manifest V3 插件的导入、`chrome.storage.local`、同步和 overlay；
7. 已用 Chromium fixture 验证导入状态、cue 查找与普通播放器 overlay；全屏和真实
   YouTube SPA 行为留给指定视频人工验收；
8. 待有可用 runtime config、`yt-dlp` 和 LLM CLI 的环境执行指定视频真实端到端验证；
9. 后续再评估音频辅助校对和本地 companion 自动调用。

## 验证计划

- Python contract/schema tests：ID、时间轴、覆盖、来源和 checkpoint identity；
- fake LLM tests：乱序、缺 ID、重复 ID、空文本、非法 JSON 和定向修复；
- 来源分支测试：人工字幕不改写，自动字幕/ASR 执行校对；
- profiling tests：验证成功、失败和 checkpoint reuse 均落盘，且不写 prompt 或字幕正文；
- 浏览器 DOM/交互测试：导入、匹配、播放、暂停、seek、倍速、全屏和 SPA 导航；
- 真实视频验证：检查 context、人名、技术术语、字幕同步和最终观看体验；
- 自动测试不调用远程 ASR/LLM，真实调用只在本地测试通过后显式执行。

## GitHub 交付流程

本功能在 `codex/bilingual-subtitle-pack` 分支开发。设计确认后执行：

1. 更新 `PROJECT_MAP.md` 中受影响的 pipeline、artifact 和扩展点事实；
2. 分阶段实现并运行最小充分本地测试；
3. commit 并 push 功能分支；
4. 使用 `gh` 创建 PR；
5. 执行 code review，修复 comments；
6. 重新运行受影响测试并更新 PR；
7. 由 User 决定是否合入 `main`。
