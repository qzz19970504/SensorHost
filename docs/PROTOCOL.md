# SDF1 V1 通讯协议

## 1. 传输模型

STM32 在 CDC 与 UART2 上使用同一种二进制帧。IIS3DWB 与 JY61P 帧在写入固定 4 KiB `SDB2` chunk 前分配传感器序号并重算 CRC。UART2 是权威排空链路；CDC 空闲且健康时镜像同一完整帧，CDC 忙或断开不阻塞 UART，也不影响 SD 回收。CLI_RESPONSE 与 STATUS 不进入 SD 队列，只返回命令来源链路。

多字节整数均为小端。UART2 上电默认 115200、8N1、无 RTS/CTS，可在 IDLE 持久化设置 9600～3000000；2/3 Mbaud 适合高吞吐排空。CDC 的波特率设置不影响 USB 实际传输。

## 2. 公共帧

| 偏移 | 长度 | 字段 | 定义 |
|---:|---:|---|---|
| 0 | 4 | magic | ASCII `SDF1` |
| 4 | 1 | version | `1` |
| 5 | 1 | message_type | `1` IIS、`2` JY、`3` STATUS、`4` CLI_RESPONSE |
| 6 | 2 | flags | 消息专用标志 |
| 8 | 2 | header_size | 固定 `28` |
| 10 | 2 | payload_size | `0..3577` |
| 12 | 4 | sequence | 全局发送序号，模 2^32 递增 |
| 16 | 8 | timestamp_us | TIM2 扩展得到的 MCU 单调微秒时间；IIS 帧在 FIFO DMA 启动前取锚 |
| 24 | 2 | item_count | payload 中逻辑项目数 |
| 26 | 2 | reserved | 固定 `0` |
| 28 | N | payload | 类型相关 |
| 28+N | 4 | crc32 | 覆盖 header+payload |

最大帧为 `28 + 3577 + 4 = 3609` 字节。

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
AT+SDCLEAR=CONFIRM
acq watermark 128|256|511
```

解析器限制单行长度、参数个数和十进制溢出。错误返回 `ERROR:<reason>` 并增加 `command_errors`。回复固定走命令来源链路。`acq start|stop`、`status` 和 watermark 作为兼容别名保留；`transport cdc|uart` 返回 `ERROR:UNSUPPORTED`。

## 7. SD 持久 FIFO 与双路输出

当前固件没有 ACK、UART 软件 credit 或 RTS/CTS。传感器帧只有在 4096 字节 chunk 和超级块提交成功后才进入 UART DMA。chunk 内所有帧逐一收到 UART DMA 完成后才整体回收；启动失败、DMA 错误、中止或掉电均保留供重试。完成事件只证明字节离开 STM32，不等价于 PC/ESP32 应用层持久化确认。

设备上电为 IDLE；`AT+START` 进入 ACQUIRE 并同时排空历史积压，`AT+STOP` 停止新采集、封存当前 chunk、进入 DRAIN，排空后回到 IDLE。队列满时停止采集并进入 DRAIN，绝不覆盖最旧未发 chunk。SD V2 使用 block 0/1 交替超级块，block 2～7 保留，block 8 起为 8 sector/4096 字节环形 chunk。旧 V1 或非空无效介质不会自动覆盖，须显式执行 `AT+SDCLEAR=CONFIRM`。

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
