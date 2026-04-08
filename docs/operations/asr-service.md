# ASR 服务运维说明

本文档描述 `yt2notion` 在远程 ASR 服务不稳定场景下的自愈配置与操作建议。

## 适用场景

- ASR 部署在独立机器（例如本地 Mac mini）
- 服务偶发卡死、超时或不可用
- 希望在进入 ASR 流程前自动重启服务，或仅在健康检查失败时重启

## 配置项

在 `config.yaml` 中配置 `extract.asr`：

```yaml
extract:
  asr:
    backend: remote
    endpoint: "http://<asr-host>:8930"
    healthcheck_path: "/health"
    healthcheck_timeout_seconds: 3.0

    # 策略 1：每次进入 ASR 流程前先重启一次
    restart_before_transcribe: true

    # 策略 2：仅当健康检查失败时重启
    restart_on_unhealthy: false

    # 在当前机器执行的重启命令（通常是 ssh 到 ASR 机器）
    restart_command: "ssh mac-mini 'cd /opt/asr && docker compose restart asr'"

    restart_readiness_timeout_seconds: 90.0
    restart_readiness_interval_seconds: 3.0
    restart_grace_seconds: 5.0
```

## 策略建议

- 推荐优先使用 `restart_before_transcribe: true`（最稳定，符合“每次 ASR 前重启”的做法）。
- `restart_on_unhealthy: true` 适合服务大多数时间稳定，仅在异常时自愈。
- 两者可同时开启；`restart_before_transcribe` 会先执行。

## 重启命令示例

### 推荐：固定脚本（避免 PATH 漂移）

在本仓库使用：

```bash
<repo_root>/scripts/asr/restart_remote_asr.sh <asr_host>
```

该脚本会：

- 固定远端 `PATH`（含 `/opt/homebrew/bin`，确保可找到 `ffmpeg`）
- 重启 `server_mlx.py`
- 启动前等待旧 `server_mlx.py` 进程和 `8930` listener 全部退出
- 启动后同时验证：`/health` 成功 + `8930` listener PID 与新进程 PID 一致

对应配置：

```yaml
extract:
  asr:
    restart_before_transcribe: true
    restart_command: "<repo_root>/scripts/asr/restart_remote_asr.sh <asr_host>"
```

### 其他示例（按你部署方式替换）

#### Docker Compose

```bash
ssh mac-mini 'cd /opt/asr && docker compose restart asr'
```

#### launchctl

```bash
ssh mac-mini 'launchctl kickstart -k gui/$(id -u)/com.example.asr'
```

#### systemd

```bash
ssh mac-mini 'sudo systemctl restart asr.service'
```

## 运行时行为

- `restart_before_transcribe=true`：首次调用 ASR 前执行一次 `restart_command`，随后等待健康检查通过。
- `restart_on_unhealthy=true`：首次调用 ASR 前先探活，失败则自动重启并等待就绪。
- 若 `healthcheck_path` 不存在（返回 404），会退化为 `restart_grace_seconds` 固定等待。

## 已发现故障模式（benchmark）

在 2026-04 的真实样本 benchmark 中，曾发现 remote ASR 重启存在“假阳性成功”窗口：

- `pkill` 后旧 listener 还短暂占用 `8930`
- 新进程尚未真正完成 bind
- 这时单看 `/health` 可能仍返回成功，导致“重启成功”被误判

`scripts/asr/restart_remote_asr.sh` 现在通过“旧进程/端口 drain + 新 PID listener 校验”规避该问题。

## 手工验证（重启语义）

在改动远程 ASR 服务或排查疑难故障时，建议按下面顺序人工验证一次：

1. 执行重启脚本  
   `scripts/asr/restart_remote_asr.sh <asr_host>`
2. 在远端确认监听者  
   `ssh <asr_host> "lsof -iTCP:8930 -sTCP:LISTEN -n -P"`
3. 在本地确认健康检查  
   `curl -fsS http://<asr_host>:8930/health`
4. 用真实音频验证一次 `/transcribe` 可用（不要只看 `/health`）  
   例如：  
   `curl -fsS -X POST "http://<asr_host>:8930/transcribe" -F "file=@/path/to/sample.mp3"`

## 常见故障排查

- 报错 `restart_command is empty`：开启了自动重启但未配置命令。
- 报错 `ASR restart command failed`：检查 SSH 免密、远端路径、权限。
- 报错 `did not become healthy after restart`：检查 `healthcheck_path` 是否正确、服务启动耗时是否超出超时配置。
- 仍然转录失败：查看 ASR 服务日志并适当增大 `restart_readiness_timeout_seconds` 与 `extract.asr.chunk_seconds`（如有配置）。
