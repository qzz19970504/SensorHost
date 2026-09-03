# SDF1 V1/V2 通讯协议

## 1. 传输模型

STM32 在 CDC 与 UART2 上使用同一种 SDF1 二进制帧。IIS3DWB 与 JY61P 在统一分流点分配 UUID、全局 sequence、时间戳并重算 CRC；原始 SDF v2 帧独立写入固定 4 KiB `SDB2` chunk，实时副本只发送到 `AT+LIVESTREAM` 选定的唯一目标链路（UART 或 CDC，冷启动默认 UART）。非目标链路不发送主动传感器帧，但仍能收发 AT 控制响应。实时链路允许丢旧保新，拥塞只增加共享的按数据源 live-drop 计数，不影响 SD 权威存档。历史帧不会随 STOP 自动发送，必须使用 `AT+EXPORT=UART|CDC` 显式上传；导出副本才设置 `ARCHIVE_EXPORT`。

多字节整数均为小端。UART2 上电默认 115200、8N1、无 RTS/CTS，可在 IDLE 持久化设置 9600～3000000；2/3 Mbaud 适合高吞吐排空。CDC 的波特率设置不影响 USB 实际传输。

## 2. 公共帧

控制帧（`STATUS`、`CLI_RESPONSE`）继续使用 V1 的 28 字节头。传感器帧使用 V2 的 44 字节头，在公共字段后增加 16 字节 UUID；两种版本共用 magic、CRC 和最大 payload 限制。

| 偏移 | 长度 | 字段 | 定义 |
|---:|---:|---|---|
| 0 | 4 | magic | ASCII `SDF1` |
| 4 | 1 | version | `1` 控制帧，`2` 传感器帧 |
| 5 | 1 | message_type | `1` IIS、`2` JY、`3` STATUS、`4` CLI_RESPONSE |
| 6 | 2 | flags | 消息专用标志 |
| 8 | 2 | header_size | 固定 `28` |
| 10 | 2 | payload_size | `0..3577` |
| 12 | 4 | sequence | 全局发送序号，模 2^32 递增 |
| 16 | 8 | timestamp_us | TIM2 扩展得到的 MCU 单调微秒时间；IIS 帧在 FIFO DMA 启动前取锚 |
| 24 | 2 | item_count | payload 中逻辑项目数 |
| 26 | 2 | reserved | 固定 `0` |
| 28 | 16 | device_uuid | 仅 V2；canonical UUID 去掉连字符后的字节顺序 |
| 44 | N | payload | V2 传感器 payload；V1 从 28 开始 |
| 28+N | 4 | crc32 | 覆盖 header+payload |

最大帧为 `44 + 3577 + 4 = 3625` 字节；V1 控制帧仍为 3609 字节上限。

CRC 使用 CRC-32/ISO-HDLC：反射多项式 `0xEDB88320`，初值 `0xFFFFFFFF`，输入/输出反射，最终异或 `0xFFFFFFFF`。它与 Python `zlib.crc32(header + payload) & 0xFFFFFFFF` 一致。

## 3. IIS3DWB FIFO（type=1）

payload 是 `item_count` 个连续的 7 字节原始 FIFO word，长度必须等于 `item_count * 7`，最大 `511` 个。

| word 偏移 | 长度 | 字段 |
|---:|---:|---|
| 0 | 1 | FIFO tag 原始字节 |
| 1 | 6 | 对应 tag 的原始数据 |

tag 位定义：`sensor_tag=tag[7:3]`、`tag_counter=tag[2:1]`、`tag_parity=tag[0]`。

- `sensor_tag=2`：加速度，数据为 `<i16 x, i16 y, i16 z>`；±2 g 下主机换算约为 `raw * 0.000061 g`。
- `sensor_tag=3`：温度，前两个数据字节为原始 `i16`。
- `sensor_tag=4`：传感器时间戳，前四个数据字节为 `u32`，每 tick 为 25 µs。
- 未定义 tag 必须保留原始数据并跳过，不得误当加速度。

flags：

- bit 0：本批读取前观察到 FIFO overrun。
- bit 1：配置启用了 FIFO timestamp batching。
- bit 2：自上一可报告批次后发生过 IIS 源侧丢弃/旧帧淘汰。

默认每 32 个 batching event 插入 timestamp word。主机扩展 32 位传感器时间戳的回绕，并用同一帧的 MCU `timestamp_us` 锚定传感器时钟到 MCU 单调时间轴，再以相邻加速度周期约 37.5 µs 重建采样时间。后续不含 timestamp tag 的帧沿用最近一次时钟偏移；新 tag 会重新校准偏移。

## 4. JY61PL（type=2）

payload 固定 14 字节、`item_count=1`：

```text
<i16 acc_x, i16 acc_y, i16 acc_z, i16 temperature,
 i16 roll, i16 pitch, i16 yaw>
```

主机换算：加速度 `raw * 16 / 32768 g`，温度 `raw / 100 °C`，角度 `raw * 180 / 32768°`。STM32 只发送原始定点值，避免传感器任务中的浮点和字符串延迟。

### 4.1 UUID、sequence 和导出标志

V2 传感器头的 UUID 是 16 字节 canonical UUID 去掉连字符后的顺序，不做整数端序翻转。未配置时由 STM32 96-bit UID 加固定命名空间 `STM32-F407-SENSOR-UUID-V1` 的 CRC32 派生；`AT+UUID=<canonical-uuid>` 可在 IDLE 持久覆盖。UUID 修改不重置 sequence，SDCLEAR 后 sequence 可重新开始。CRC32 覆盖完整 V2 头和 payload。

`ARCHIVE_EXPORT` 为 flags 的 bit 15。SD 中保存的原始帧不带此位；EXPORT 只在 RAM 副本上设置并重算 CRC，绝不改写 SD。

## 5. STATUS（type=3）

payload 固定 64 字节、`item_count=1`：

| 偏移 | 类型 | 字段 |
|---:|---|---|
| 0 | u8 | status_version=`1` |
| 1 | u8 | active_transport：CDC=`1`，UART=`2` |
| 2 | u8 | pending_transport：无=`0`，CDC=`1`，UART=`2` |
| 3 | u8 | acquisition_state：停止=`0`，运行=`1`，配置失败安全态=`2` |
| 4 | u16 | watermark_words |
| 6 | u16 | free_data_buffers |
| 8 | u32 | legacy_uart_credit，固定 `0`（保留 V1 二进制布局） |
| 12 | u32 | data_queue_peak |
| 16 | u32 | fifo_overruns |
| 20 | u32 | source_drops |
| 24 | u32 | transport_drops |
| 28 | u32 | spi_dma_errors |
| 32 | u32 | uart_dma_errors：UART2 发送 DMA 错误（core）+ App_Jy61pl UART DMA + Control UART RX 错误 |
| 36 | u32 | cdc_errors：CDC 后端发送启动失败（cdc_start_failures）次数 |
| 40 | u32 | command_errors |
| 44 | u16 | IIS 任务最小剩余栈，word |
| 46 | u16 | Transport 任务最小剩余栈，word |
| 48 | u16 | Control 任务最小剩余栈，word |
| 50 | u16 | JY61PL 任务最小剩余栈，word |
| 52 | u16 | LED/System 任务最小剩余栈，word |
| 54 | u16 | reserved=`0` |
| 56 | u64 | uptime_us |

计数器饱和于 `UINT32_MAX`。`source_drops`（偏移 20）包括无空闲帧、存储入口已满、SD 写入失败或裸扇区队列已满。`transport_drops`（偏移 24）= `uart_start_failures` + `cdc_start_failures`（饱和加），即 UART 后端启动失败 + CDC 后端启动失败；不含 `uart_dma_errors`（专属偏移 32，避免与偏移 24 双重计数），也不含实时丢旧保新与 STOP quiesce 丢弃（这两类按数据源计入 `+LIVE` 行的 `DROPS_IIS`/`DROPS_JY`）；正常负载且链路可用时增量为 0；`AT+LIVESTREAM=CDC` 而 CDC 未连接时会持续增长，属预期诊断信号。`uart_dma_errors`（偏移 32）= UART2 发送 DMA 错误（core）+ App_Jy61pl UART DMA 错误 + Control UART RX 错误，是 UART 目标实时验收 `physical_tx_error_delta` 门限的字段来源。`cdc_errors`（偏移 36）= CDC 后端发送启动失败（`cdc_start_failures`），是 CDC 目标实时验收 `physical_tx_error_delta` 门限的字段来源；自本轮固件起真正赋值，不再恒 0。偏移 8 不再表示可用流控额度，接收端必须忽略其数值。

## 6. CLI_RESPONSE（type=4）

payload 是 UTF-8 文本，通常以 `\r\n` 结尾。CLI 输入本身不是 SDF1 帧，而是发送到任一控制入口的行文本：

```text
AT
AT+START
AT+STOP
AT+STATE?
AT+BAUD?
AT+BAUD=<9600..3000000>
AT+UUID?
AT+UUID=<canonical-uuid>
AT+LIVESTREAM?
AT+LIVESTREAM=UART|CDC
AT+EXPORT[=UART|CDC]
AT+SDCLEAR=CONFIRM
acq watermark 128|256|511
```

解析器限制单行长度、参数个数和十进制溢出。错误返回 `ERROR:<reason>` 并增加 `command_errors`。回复固定走命令来源链路。`acq start|stop`、`status` 和 watermark 作为兼容别名保留；`transport cdc|uart` 返回 `ERROR:UNSUPPORTED`。状态查询（`AT+STATE?`）的发送降级分两类：格式化超出 CLI 预算返回 `ERROR:RESPONSE_TOO_LARGE`；控制缓冲池耗尽时固件尽力返回 `ERROR:TX_BUSY`（计 `command_errors`），但该回复本身同样需要缓冲，主导失败模式下主机通常只观察到响应超时（详见 §6.1）。对幂等状态查询应退避重试而非笼统失败。

### 6.1 AT+LIVESTREAM

`AT+LIVESTREAM?`（查询，全状态可用）返回 `+LIVESTREAM:UART` 或 `+LIVESTREAM:CDC`。

`AT+LIVESTREAM=UART` / `AT+LIVESTREAM=CDC`（设置，仅 IDLE）：

- 成功：`OK`
- 非 IDLE 且目标与当前不同：`ERROR:STATE`
- 非 IDLE 且目标与当前相同：幂等 `OK`
- 无效目标（非 UART/CDC、非大写）：`ERROR:ARGUMENT`
- IDLE 但仍有在途实时传输：`ERROR:BUSY`（瞬态；主机应退避后有限次重试，不得立即当致命错误抛 `RuntimeError`）
- 状态响应格式化超出 CLI 预算：`ERROR:RESPONSE_TOO_LARGE`（主机以 `ValueError` 结构化诊断）
- 控制缓冲池耗尽/发送降级：固件**尽力**回复 `ERROR:TX_BUSY`（计 `command_errors`），但该回复本身同样需要控制缓冲；主导失败模式下主机通常观察到**响应超时**并伴随 `command_errors` 增量，未必能收到 `ERROR:TX_BUSY` 文本。主机应以「响应超时 + `command_errors` 增量」作为该条件的判据，不要假定一定能收到 `ERROR:TX_BUSY`。对幂等查询（`AT+STATE?` / `AT+LIVESTREAM?` 等）可退避重试；对非幂等命令（`AT+STOP` / `AT+START` / `AT+SDCLEAR` / `AT+EXPORT`）**不得重发**——命令已执行、重发会被拒为 `ERROR:STATE`（对应主机 `command(idempotent=False)`）。

冷启动默认 UART，设置不持久化（掉电后恢复 UART）。实时副本只发送到选定目标；非目标链路仍收发 AT 控制响应，但不接收主动传感器帧。CDC 被选中但主机未连接时，不自动回退 UART。

> 移除声明：本次移除尚未发布的 `AT+CDCSTREAM?` / `AT+CDCSTREAM=ON` / `AT+CDCSTREAM=OFF` 与 `DRAIN` 状态，实时目标改由 `AT+LIVESTREAM` 显式互斥选择；向固件发送这些已移除命令返回 `ERROR:ARGUMENT`。

`AT+STATE?` 的 `+SD` 行同时返回 `READY=0|1` 和 `FORMAT_REQUIRED=0|1`。恢复扫描完成并可接受采集、清理或导出请求后 `READY=1`；介质需要显式格式化时 `FORMAT_REQUIRED=1`。上位机在开始验收或采集前必须等待 `READY=1`。

`AT+STATE?` 的 `+LIVE` 行返回实时流状态：

```text
+LIVE:TARGET=<UART|CDC>,DROPS_IIS=<n>,DROPS_JY=<n>,LAST_ROUTED_SEQUENCE=<n>,LAST_COMPLETED_SEQUENCE=<n>
```

- `TARGET`：当前实时目标链路。
- `DROPS_IIS` / `DROPS_JY`：共享按数据源 live-drop 计数，切换目标不清零（验收使用快照差值）。
- `LAST_ROUTED_SEQUENCE`：Router 最近分配给实时候选的序号。
- `LAST_COMPLETED_SEQUENCE`：Scheduler 最近完成物理发送的序号。
- 主机按无符号 32-bit 环绕差计算滞后（routed - completed），验收要求滞后不持续 > 64 帧。

`AT+STATE?` 还返回 `+STOP_REASON:<NONE|COMMAND|BUFFER_FULL|STORAGE_ERROR>` 行。其中 `BUFFER_FULL` 为历史保留值：当前固件在 SD 满时保持 `ACQUIRE` 并循环覆盖最旧 chunk（`CONTROL_EVENT_BUFFER_FULL` 分支为 no-op，不再停止采集），因此正常运行不会再产生 `BUFFER_FULL`；枚举保留仅为兼容旧记录，不要在固件侧删除。

### 6.2 实时验收门限（live-uart / live-cdc）

`host/tools/realtime_archive_acceptance.py --mode live-uart|live-cdc` 使用 `LiveAcceptance` 模型判定，两种目标共享的**硬门限**为：目标链路有传感器帧、非目标链路主动传感器帧为 0、送达帧 CRC/header/length/payload 错误为 0、物理发送错误增量为 0（D1 字段来源：UART 目标取偏移 32 `uart_dma_errors` 增量、CDC 目标取偏移 36 `cdc_errors` 增量）、`source_drop` 增量为 0、STOP→OK 耗时 ≤2 s、**STOP 的 OK 返回之后**目标与非目标链路新增主动传感器帧为 0（`post_stop_sensor_frames==0`）、以及（适用时）非目标链路 `AT`/`AT+STATE?` 探测成功。`max_sequence_lag` 自 115200 抽帧实时模型起**不再是硬门限**，改为上报的新鲜度诊断证据（见下）。

`post_stop_sensor_frames` 门限以“收到 STOP 的 OK 的时刻”为基线度量，而非以“写入 AT+STOP 之前”为基线：固件设计明确允许 STOP 时唯一在途实时帧自然完成（该帧在返回 OK 之前发完），`live_inhibited` 闩锁保证 OK 之后不再有新主动帧。因此把握手期（`AT+STOP` 写入 → 收到 OK）内完成的这条在途帧计入 `post_stop` 会导致 `post_stop>=1` 恒成立的假失败。握手窗口内出现的主动传感器帧数改由**软诊断字段** `handshake_inflight_frames`（预期 ≤1）记录到结果 JSON，仅供观测，不参与 `passed` 判定。

**115200 抽帧实时模型（用户批准的需求重定义）**：实机上位机经 ESP32 网关以 115200 接收设备 UART。UART/CDC 实时链路只保证**实时新鲜度**——采用丢旧保新（newest-wins）送达最新帧，带宽不足时大量 live-drop 与较大的 routed-vs-completed 滞后属物理预期、允许且不判负；SD 存档保证**完整权威**（`source_drop=0`）。因此 `max_sequence_lag` 已从 `passed` 硬门限移除，改与送达帧率（`target_frames/duration`）一起写入结果 JSON 的 `freshness_diagnostics`，作为新鲜度证据而非门限。上述真实不变量（`source_drop=0`、送达帧协议错误为 0、物理发送错误为 0、非目标静默、STOP 双完成、OK 后零主动帧、CDC live-drop=0）仍为硬门限；不得为迁就带宽而降低采样率或隐藏 `source_drop`。

live-drop 门限按目标区分（关键差异）：

- **CDC 目标**：要求 `DROPS_IIS` 与 `DROPS_JY` 增量均为 0（正常负载下 CDC 无损）。
- **UART 目标**：允许实时丢旧保新，`DROPS_IIS`/`DROPS_JY` 增量可为正而不判失败；UART 目标只由上面的共享硬门限（尤其 `source_drop=0`、送达帧协议/物理错误为 0）约束，`max_sequence_lag` 仅作新鲜度诊断。

**控制链路与单向 UART bench**：新增 `--control-link {cdc,uart}`（默认 `cdc`）与 `--uart-host-to-device-absent`（默认 True）。当前 bench 只接了 UART 上传方向（device→host，Y+/Z-），host→device UART 物理未接，故控制与 50 ms 轮询恒走 CDC：`live-uart` 数据监听 UART、控制走 CDC、非目标 CDC 应无主动传感器帧（`nontarget_frames==0`）并照常探测其 `AT`/`AT+STATE?` 响应；`live-cdc` 数据在 CDC、控制也走 CDC（USB 带宽足够、争用可忽略）、非目标 UART 只以**监听**校验静默（`nontarget_frames==0`）。当非目标链路是 UART 且 host→device 缺失时无法向其发 `AT`，该非目标探测标记为 N/A（结果 JSON `nontarget_at_probe_applicable=false`），不因发不出而判负；接上 UART TX 后用 `--no-uart-host-to-device-absent` 恢复该探测为硬门限。UART 端由 `PortReader` 独立后台线程持续 drain，主线程轮询 CDC 不会阻塞 UART 读取，故 CRC/discard 只反映链路真实情况而非主机来不及读造成的假错。

## 7. SD 持久存档、实时分流与历史导出

当前固件没有 ACK、UART 软件 credit 或 RTS/CTS。实时流使用在途帧不可覆盖的双槽丢旧保新队列，只发送到 `AT+LIVESTREAM` 选定的唯一目标。CDC 被选中但未连接时不自动回退 UART。任一实时链路启动失败、DMA 错误或拥塞只丢实时副本并累计共享的按数据源 drop 计数（DROPS_IIS/DROPS_JY），SD 所有权不受影响。完成事件只证明字节离开 STM32，不等价于 PC/ESP32 应用层持久化确认。

设备上电为 IDLE；`AT+START` 进入 ACQUIRE，`AT+STOP` 进入 STOPPING，同时触发 SD flush 与 Live quiesce。仅当 STORAGE_FLUSHED 与 LIVE_QUIESCED 两事件都到达（任意顺序）才进 IDLE 并在原命令来源返回 OK。Live 侧丢弃并统计待发实时副本、等待唯一在途帧完成。STOP 不上传历史。进入 IDLE 后设备保证不再主动发送传感器帧（固件 live 抑制闩锁），该保证只由下一次 `AT+START` 解除；`AT+EXPORT` 的历史帧不受此约束。SD V2 使用 block 0/1 交替超级块，block 2～7 保留，block 8 起为 8 sector/4096 字节环形 chunk。介质满时覆盖最旧 chunk，累计 `OVERWRITTEN_CHUNKS/FRAMES`，采集保持 ACQUIRE。

IDLE 下 `AT+EXPORT=UART|CDC` 进入 EXPORT，从最旧 chunk 开始发送；命令来源端返回 `EXPORT_BEGIN` 和 OK，完成返回 `EXPORT_END:CHUNKS=n,FRAMES=n`，空存档返回 `EXPORT_EMPTY`。目标链路错误、START、STOP 或掉电会中止并保留当前 chunk，返回 `EXPORT_ABORTED`；重新导出从该 chunk 第一帧开始，允许最多重复一个 chunk，不能漏帧。UART 与 CDC 导出目标严格隔离，CDC 导出时 CLI_RESPONSE 可与历史帧交错。

## 8. 接收端重同步

推荐解析步骤：

1. 搜索 `SDF1`，只保留可能构成下一 magic 的末尾 3 字节。
2. 等待 28 字节公共头；拒绝 header_size 或 payload_size 越界的候选，并从候选首字节后重新搜索。V1 要求 `header_size=28`，未来版本允许 `28..256`。
3. 等待 `header_size + payload_size + 4` 字节。
4. CRC 错误时从候选首字节后重搜，不按错误长度盲跳。
5. CRC 正确后再解释 version/type；未知 version 或 type 都计数并按已验证的完整长度跳过，payload 内出现 `SDF1` 不会造成误锁定。
6. 只用 IIS/JY 传感器帧的 sequence 统计缺口并处理回绕；CLI/STATUS 不推进基线。

仓库中的 `test/protocol.py` 是参考实现。

## 9. Golden frames

`test/golden/stream_v1_frames.bin` 连续包含四个完整帧；`stream_v1_frames.json` 给出边界和期望值：

| 名称 | offset | length | type | sequence | CRC32 |
|---|---:|---:|---:|---:|---:|
| iis3dwb_fifo | 0 | 46 | 1 | 1 | 4161595075 |
| jy61pl_sample | 46 | 46 | 2 | 2 | 3585562361 |
| status | 92 | 96 | 3 | 3 | 3149268224 |
| cli_response | 188 | 47 | 4 | 4 | 4065152228 |

完整编码可复现：

```powershell
python .\test\generate_golden_frames.py
git diff --exit-code -- .\test\golden
```

完整流式解码：

```python
from pathlib import Path
from protocol import StreamParser

parser = StreamParser()
frames = []
data = Path("test/golden/stream_v1_frames.bin").read_bytes()
for byte in data:
    frames.extend(parser.feed(bytes([byte])))
assert [frame.sequence for frame in frames] == [1, 2, 3, 4]
```

## 10. ESP32/PSRAM 参考流程

完整的 ESP32 模块边界、状态机、PSRAM 所有权、故障恢复和验收要求见 [ESP32_GATEWAY_REQUIREMENTS.md](./ESP32_GATEWAY_REQUIREMENTS.md)。本节只提供协议级参考，若两者对线缆字节定义的描述不一致，以本文前 9 节为准。

ESP32 应把 UART 字节视为透明 SDF1 流，先写 PSRAM 环形缓冲，再由网络/存储消费者释放空间。不要按 UART read 边界假设帧边界。STM32 不等待 ESP32 确认，因此 ESP32 必须持续提供足够的 RX 服务能力，并显式报告本地溢出。

```text
on_boot:
    uart_config(3_000_000, 8N1, no_rts_cts)
    parser.reset()

loop:
    bytes = uart_read()
    accepted = psram_ring.write_without_overwrite(bytes)
    parser.feed_for_crc_and_metrics(bytes[0:accepted])
    if accepted != len(bytes):
        record_rx_overflow(len(bytes) - accepted)

when consumer_commits(n):
    psram_ring.release(n)
```

PSRAM 满时不能通过命令暂停 STM32；首版应把容量和消费者吞吐设计为能承受最长业务阻塞时间。若业务需要可证明的端到端不丢失或可控背压，必须在后续协议中增加接收确认/窗口机制，不能把 UART DMA 完成当作对端确认。
