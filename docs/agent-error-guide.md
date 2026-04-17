# Agent Error Guide

## Goal

当用户说“帮我检查最近一次错误”时，AI 必须先找 job，再读 job metadata 和 log，再根据本文档翻译结论。

## Command Workflow

1. `uv run yt2notion agent list`
2. 找最近一个 `failed` 的 `job_id`
3. `uv run yt2notion agent show <job_id>`
4. `uv run yt2notion agent logs <job_id>`
5. 结合本文档输出结论

## Runtime Files

- `~/.yt2notion-agent/jobs/<job_id>.json`
- `~/.yt2notion-agent/logs/<job_id>.log`

## How to Read the Files

- `agent list`: 找最近 `failed`
- `agent show`: 看 `status`、`error`、`current_step`、`workspace_dir`
- `agent logs`: 看原始报错和尾部 `FAILURE SUMMARY`

## Error Catalog

| pattern | step | substep | meaning | retry advice | next action |
| --- | --- | --- | --- | --- | --- |
| `SSL: UNEXPECTED_EOF_WHILE_READING` | `download` | `metadata` | Apple 页面或 TLS 链路波动 | `safe` | 先重试；连续出现再检查 `yt-dlp`、网络或站点状态 |
| `HTTP Error 403: Forbidden` | `download` | `audio_download` | 音频源被 block、风控，或 cookies / headers 不满足 | `limited` | 可有限重试；若持续复现，再检查 cookies 或提取逻辑 |
| `yt-dlp not found` | `download` | `tooling` | 本机缺少 `yt-dlp` 可执行文件 | `no` | 安装或修正运行环境 |
| `No subtitles and no ASR endpoint configured` | `transcribe` | `asr_config` | 没字幕，且没有可用 ASR 配置 | `no` | 补 `extract.asr.endpoint` 或调整提取策略 |
| `ASR request failed` | `transcribe` | `asr_request` | ASR 服务不可达，或请求失败 / 5xx | `limited` | 先看服务状态，再决定是否重试 |
| `Failed after 3 attempts: Command '['codex'` | `extract` or `summarize` | `codex_exec` | Codex CLI 调用反复失败 | `limited` | 先看 profile、model、config，再决定是否重试 |
| `profile` / `config` / `model` related Codex errors | `extract` or `summarize` | `codex_config` | Codex profile 或 model 配置无效 | `no` | 改配置，不要盲重试 |

## Unknown Error Handling

- 先保留原始错误短句
- 从 `agent show` 和 `agent logs` 判断失败节点
- 如果没有命中已知模式，明确返回 `unknown`
- 说明这代表需要后续补 guide 条目或补 log hint

