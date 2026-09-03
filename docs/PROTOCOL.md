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
| 32 | u32 | uart_dma_errors（UART1+UART2） |
| 36 | u32 | cdc_errors/busy 次数 |
| 40 | u32 | command_errors |
| 44 | u16 | IIS 任务最小剩余栈，word |
| 46 | u16 | Transport 任务最小剩余栈，word |
| 48 | u16 | Control 任务最小剩余栈，word |
| 50 | u16 | JY61PL 任务最小剩余栈，word |
| 52 | u16 | LED/System 任务最小剩余栈，word |
| 54 | u16 | reserved=`0` |
| 56 | u64 | uptime_us |

计数器饱和于 `UINT32_MAX`。`source_drops` 包括无空闲帧、存储入口已满、SD 写入失败或裸扇区队列已满；`transport_drops` 包括发送切换、中止及传输队列/小缓冲失败。偏移 8 不再表示可用流控额度，接收端必须忽略其数值。

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

解析器限制单行长度、参数个数和十进制溢出。错误返回 `ERROR:<reason>` 并增加 `command_errors`。回复固定走命令来源链路。`acq start|stop`、`status` 和 watermark 作为兼容别名保留；`transport cdc|uart` 返回 `ERROR:UNSUPPORTED`。

### 6.1 AT+LIVESTREAM

`AT+LIVESTREAM?`（查询，全状态可用）返回 `+LIVESTREAM:UART` 或 `+LIVESTREAM:CDC`。

`AT+LIVESTREAM=UART` / `AT+LIVESTREAM=CDC`（设置，仅 IDLE）：

- 成功：`OK`
- 非 IDLE 且目标与当前不同：`ERROR:STATE`
- 非 IDLE 且目标与当前相同：幂等 `OK`
- 无效目标（非 UART/CDC、非大写）：`ERROR:ARGUMENT`

冷启动默认 UART，设置不持久化（掉电后恢复 UART）。实时副本只发送到选定目标；非目标链路仍收发 AT 控制响应，但不接收主动传感器帧。CDC 被选中但主机未连接时，不自动回退 UART。

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

## 7. SD 持久存档、实时分流与历史导出

当前固件没有 ACK、UART 软件 credit 或 RTS/CTS。实时流使用在途帧不可覆盖的双槽丢旧保新队列，只发送到 `AT+LIVESTREAM` 选定的唯一目标。CDC 被选中但未连接时不自动回退 UART。任一实时链路启动失败、DMA 错误或拥塞只丢实时副本并累计共享的按数据源 drop 计数（DROPS_IIS/DROPS_JY），SD 所有权不受影响。完成事件只证明字节离开 STM32，不等价于 PC/ESP32 应用层持久化确认。

设备上电为 IDLE；`AT+START` 进入 ACQUIRE，`AT+STOP` 进入 STOPPING，同时触发 SD flush 与 Live quiesce。仅当 STORAGE_FLUSHED 与 LIVE_QUIESCED 两事件都到达（任意顺序）才进 IDLE 并在原命令来源返回 OK。Live 侧丢弃并统计待发实时副本、等待唯一在途帧完成。STOP 不上传历史。SD V2 使用 block 0/1 交替超级块，block 2～7 保留，block 8 起为 8 sector/4096 字节环形 chunk。介质满时覆盖最旧 chunk，累计 `OVERWRITTEN_CHUNKS/FRAMES`，采集保持 ACQUIRE。

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
