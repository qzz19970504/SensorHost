# 实时链路速率优化（2026-09-17）

## 目标与结果

上位机实时波形峰值从 ~3,641 samples/s（且明显卡顿）提升到 **~8,000 samples/s**（解析型消费端实测 7,811–8,186；裸 TCP 消费端 69,634 B/s ≈ 9,821 samples/s 当量）。卡顿消除（解析不再反压）。

| 阶段 | 改动 | 裸 TCP 交付 | 解析端到端 |
|---|---|---:|---:|
| 基线 | UART 460800 + ESP32 256B 段 + LWIP 窗口 5760 + 主机逐样本 Python 解析 | 30,221 B/s | 2,795 samples/s |
| +ESP32 大包 | `UART_PT_MAX_PAYLOAD_SIZE` 256→1440；`LWIP_TCP_SND_BUF/WND` 5760→16384 | 40,110 B/s | — |
| +双端 921600 | ESP32 `CONFIG_BRIDGE_UART_BAUD_RATE`=921600；STM32 `AT+BAUD=921600`（持久化） | 69,634 B/s | — |
| +主机向量化 | SensorHost IIS 解码 numpy 化（`iis_samples`/`iis_words` 改为按需物化 property） | — | 7,811–8,186 samples/s |

## 瓶颈定位方法（可复用）

三段式对照测量，逐跳定瓶颈：
1. STM32→ESP32：ESP32 调试口（USB Serial/JTAG）每秒统计 `uart_rx_bytes/s`；
2. ESP32→PC：同统计的 `tcp_tx_bytes/s` + `tcp_enqueue_dropped` 增速（队列饱和即该跳封顶）；
3. PC 消费：裸 recv 计字节（`raw_tcp_sink.py`）与解析型消费（`wifi_rate_probe.py`）之差 = 主机解析开销。

基线读数：uart_rx 40KB/s（460800 线速饱和）、tcp_tx 30KB/s 且 enq_drop ~250/s（WiFi 跳封顶）、解析消费 ~20–26KB/s（主机反压）。

## 各端改动

### ESP32（分支 feat/tcp-large-segments）
- `components/uart_pt/include/uart_pt.h`：`UART_PT_MAX_PAYLOAD_SIZE` 256→1440（TCP 段变大，软 AP 上每段开销占比下降）；README 同步。
- `sdkconfig` / `sdkconfig.defaults`：`CONFIG_LWIP_TCP_SND_BUF_DEFAULT`、`CONFIG_LWIP_TCP_WND_DEFAULT` 5760→16384；`CONFIG_BRIDGE_UART_BAUD_RATE` 460800→921600。
- 烧录：`idf.py -p COM20 flash`（USB Serial/JTAG）。

### STM32（无代码改动）
- `AT+BAUD=921600` 经 CDC 下发并持久化（sector 7 config），与 ESP32 对齐。
- 固件本身未改：921600 下 UART 供给 ~80KB/s 有效，已高于 WiFi 跳 ~70KB/s，不再封顶。

### SensorHost（分支 feat/fast-iis-decode）
- `protocol/sdf1.py`：7 字节 FIFO 字用重叠 union 结构化 dtype 一次性 `frombuffer`；时间戳重建改为向量化分段算法（语义与旧逐字 walker 完全一致，golden 测试证明）；`Frame.iis_samples`/`iis_words` 改为按需物化 property，热路径只持有 numpy 数组。
- `acquisition/sample_store.py`：新增 `append_iis_arrays`；`append_iis` 转调。
- `acquisition/controller.py`、`presentation/playback_controller.py`：优先消费数组路径。
- 门禁：`pytest tests -q` → 308 passed。

## 剩余上限与后续可选

- 当前端到端受 WiFi 跳 ~70KB/s 封顶（2.4G 软 AP）；再提升需：降字节/样本（协议级，涉及 SD 格式兼容，风险中高）、或改善 RF 环境（信道/距离）、或改 5G 网关硬件（ESP32-S3 不支持）。
- UART 已有余量（921600 → 可供 80KB/s）；如 WiFi 后续提升可再评估 1.5M/3M。
- 诊断探针（本仓库 build/ 下，gitignore）：`raw_tcp_sink.py`、`wifi_rate_probe.py`、`esp32_stats_monitor.py`。
