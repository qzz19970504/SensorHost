# 实时链路速率优化（2026-09-17）

## 目标与结果

上位机实时波形峰值从 ~3,641 samples/s（且明显卡顿）提升到 **~6,400–6,800 samples/s**，且 **crc_errors=0**（无 CRC 风暴、无卡顿）。解析型消费端吃满线速（48,897 B/s = 576000 波特线速上限）。

| 阶段 | 改动 | goodput | 解析端到端 | crc |
|---|---|---:|---:|---:|
| 基线 | UART 460800 + ESP32 256B 段 + LWIP 窗口 5760 + 主机逐样本解析 + feed 逐帧头部删除 | 30,221 B/s | 2,795 samples/s | 0 |
| +ESP32 大包/窗口 | 块 256→1440；LWIP snd/wnd→16384（后 65535） | 40,110 B/s | — | 0 |
| +主机向量化 | numpy union dtype 解码 + 数组消费路径 | — | 7,811–8,186 samples/s（921600 档） | 视波特率 |
| +feed 游标化 | 去除逐帧 `del buffer[:n]` 的 O(n²) 头部 memmove | — | 吃满线速 | — |
| +波特率定档 | 576000（双端） | 48,897 B/s | **6,442 samples/s** | **0** |

## 波特率定档实验（关键结论）

透明桥架构下 **UART 线速必须 ≤ WiFi Sink 速率**，否则 ESP32 只能按 1440B 块丢弃，丢在帧中间 → 主机 CRC 风暴 → 卡顿：

| 波特率 | 线速 | 实测 goodput | crc/12s | 结论 |
|---:|---:|---:|---:|---|
| 460800 | 46 KB/s | 39.4 KB/s | 0 | 干净但封顶低 |
| 576000 | 57.6 KB/s | 48.8–48.9 KB/s | 0 | **定档：干净且接近 Sink** |
| 640000 | 64 KB/s | 48.3 KB/s | 0 | 与 576000 同速，Sink 下探时盈余更大 |
| 921600 | 92 KB/s | 27–56 KB/s | 83–216 | 持续盈余→块丢弃→CRC 风暴=卡顿，弃 |
| 1500000 | 150 KB/s | — | fifo_ovf 增长 | ESP32 RX 硬件 FIFO 溢出，弃 |

WiFi Sink 本身波动约 48–70 KB/s（2.4G 软 AP）；576000 在 Sink 下探时盈余最小，是"最快且稳"的平衡点。

## 各端改动

### ESP32（分支 feat/tcp-large-segments）
- `components/uart_pt/include/uart_pt.h`：`UART_PT_MAX_PAYLOAD_SIZE` 256→1440；README 同步。
- `components/uart_pt/uart_pt.c`：RX/upstream 任务优先级 8→12。
- `main/main.c`：`rx_buffer_size=8192`、`event_queue_size=40`。
- `sdkconfig.defaults`：`CONFIG_BRIDGE_UART_BAUD_RATE=576000`、`CONFIG_LWIP_TCP_SND_BUF/WND_DEFAULT=65535`、`CONFIG_BRIDGE_UART_BLOCK_COUNT=16`。
- 烧录：`idf.py -p COM20 flash`（USB Serial/JTAG）。注意 `scripts/build.ps1` 的 `ErrorActionPreference=Stop` 会被 IDF 环境脚本 stderr NOTE 误杀，需手动 `. scripts/esp-idf-environment.ps1; Initialize-BridgeEspIdfEnvironment` 后直接 `idf.py build`。

### STM32（无代码改动）
- `AT+BAUD=576000` 经 CDC 下发并持久化（sector 7 config）。

### SensorHost（分支 feat/fast-iis-decode）
- `protocol/sdf1.py`：7 字节 FIFO 字用重叠 union 结构化 dtype 一次性 `frombuffer`；时间戳重建向量化分段（语义与旧逐字 walker 一致，golden 证明）；`iis_samples`/`iis_words` 改按需物化 property；`feed()` 改游标解析+单次批量压缩（去除 O(n²) 头部 memmove）。
- `acquisition/sample_store.py`：新增 `append_iis_arrays`；`acquisition/controller.py`、`presentation/playback_controller.py` 优先数组路径。
- 门禁：`pytest tests -q` → 308 passed。

## 剩余上限与后续可选

- 端到端受 WiFi Sink（48–70 KB/s 波动）封顶；再提升需协议级降字节/样本（新增 packed 消息类型，7.22→6.09 B/sample ≈ +18%，涉及 SD 格式与双端解析，风险中）或改善 RF/换 5G 网关。
- 诊断探针（固件仓库 build/ 下，gitignore）：`raw_tcp_sink.py`（裸 recv）、`wifi_rate_probe.py`（解析+样本率）、`crc_probe.py`（goodput+crc）、`esp32_stats_monitor.py`（逐跳统计）。
