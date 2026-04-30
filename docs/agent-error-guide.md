# Agent Error Guide

## Goal

当用户说“帮我检查最近一次错误”时，AI 必须先找 job，再读 job metadata 和 log，再根据本文档翻译结论。

## Command Workflow

1. `uv run yt2notion agent list`
2. 找最近一个 `failed` 的 `job_id`
3. `uv run yt2notion agent show <job_id>`
4. `uv run yt2notion agent logs <job_id>`
5. 如果失败节点是 `transcribe`，且 `workspace_dir` 存在，再读 `<workspace_dir>/transcribe_state.json`
6. 结合本文档输出结论

## Runtime Files

- `~/.yt2notion-agent/jobs/<job_id>.json`
- `~/.yt2notion-agent/logs/<job_id>.log`
- `<workspace_dir>/transcribe_state.json`（仅当失败节点是 `transcribe` 时）

## How to Read the Files

- `agent list`: 找最近 `failed`
- `agent show`: 看 `status`、`error`、`current_step`、`workspace_dir`
- `agent logs`: 看原始报错和尾部 `FAILURE SUMMARY`
- `transcribe_state.json`: 看 `status`、`job_mode`、`next_attempt_at`、`ash_defer_count`、`chunks[*].status/backend_used/attempts`

## Transcribe Checkpoint Readout

当失败节点是 `transcribe`，或者日志里出现 `transcribe:chunk_started` / `transcribe:hourly_wait` / `transcribe:daily_fallback_switch` / `transcribe:chunk_completed` 时，必须额外读取 `transcribe_state.json`。

优先看这些字段：

- `status = "waiting_ash"`：当前不是普通崩溃，而是在等 Groq hourly window 过去
- `next_attempt_at`：下一次允许重试的时间
- `ash_defer_count`：已经被 hourly limit 延后过多少次
- `job_mode = "remote_remaining"`：已经触发过 ASD，剩余 chunk 改走 remote
- `chunks[*].status`：哪些 chunk 已完成，哪些还 pending
- `chunks[*].backend_used`：每个已完成 chunk 实际走的是 `groq` 还是 `remote`

日志里的 transcribe 事件含义：

- `transcribe:chunk_started`：开始跑某个 chunk，payload 里会带 `chunk_id`、区间、backend、attempt
- `transcribe:hourly_wait`：命中 ASH，payload 里会带 `retry_after_seconds`、`next_attempt_at`
- `transcribe:daily_fallback_switch`：命中 ASD，payload 里会带当前 chunk 和本次切到 fallback 的受影响 chunk 列表
- `transcribe:chunk_completed`：某个 chunk 已完成，payload 里会带 `backend` 和 `entries_count`

## Error Catalog

| pattern | step | substep | meaning | retry advice | next action |
| --- | --- | --- | --- | --- | --- |
| `SSL: UNEXPECTED_EOF_WHILE_READING` | `download` | `metadata` | Apple 页面或 TLS 链路波动 | `safe` | 先重试；连续出现再检查 `yt-dlp`、网络或站点状态 |
| `HTTP Error 403: Forbidden` | `download` | `audio_download` | 音频源被 block、风控，或 cookies / headers 不满足 | `limited` | 可有限重试；若持续复现，再检查 cookies 或提取逻辑 |
| `yt-dlp not found` | `download` | `tooling` | 本机缺少 `yt-dlp` 可执行文件 | `no` | 安装或修正运行环境 |
| `No subtitles and no ASR endpoint configured` | `transcribe` | `asr_config` | 没字幕，且没有可用 ASR 配置 | `no` | 补 `extract.asr.endpoint` 或调整提取策略 |
| `ASR request failed` | `transcribe` | `asr_request` | ASR 服务不可达，或请求失败 / 5xx | `limited` | 先看服务状态，再决定是否重试 |
| `Groq daily quota exceeded` | `transcribe` | `groq_daily_limit` | Groq 当天额度用完；如果配置了 fallback，通常会切到 `remote_remaining`，没配置则直接失败 | `no` | 先看 `transcribe_state.json` 是否已经切 fallback；若没有 fallback，就补配置或隔天再跑 |
| `Missing transcribe chunk result` | `transcribe` | `checkpoint_state` | checkpoint 文件与状态不同步，chunk payload 丢失或被清理 | `safe` | 先看 `transcribe_state.json` 与 `transcribe_chunks/`，再从 `transcribe` 重试 |
| `Failed after 3 attempts: Command '['codex'` | `extract` or `summarize` | `codex_exec` | Codex CLI 调用反复失败 | `limited` | 先看 profile、model、config，再决定是否重试 |
| `profile` / `config` / `model` related Codex errors | `extract` or `summarize` | `codex_config` | Codex profile 或 model 配置无效 | `no` | 改配置，不要盲重试 |

## Unknown Error Handling

- 先保留原始错误短句
- 从 `agent show` 和 `agent logs` 判断失败节点
- 如果失败节点是 `transcribe`，必须额外结合 `transcribe_state.json`
- 如果没有命中已知模式，明确返回 `unknown`
- 说明这代表需要后续补 guide 条目或补 log hint
