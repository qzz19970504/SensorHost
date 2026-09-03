# ESP32 通讯网关交接需求

> ESP32 通过无硬件流控的 UART 接收 STM32 的 SDF1 数据流（生产验收可将 UART2 配置为 3 Mbaud），以 PSRAM 吸收接收与上行业务之间的抖动，并把原始帧透明交给后续消费者。

**Module:** Sensor Acquisition / ESP32 Gateway

**Status:** Planned

**Updated:** 2026-09-01

## 1. 当前 STM32 合同

生产固件运行在 STM32F407VET6（LQFP100）。IIS3DWB 与 JY61PL 在统一分流点编码为 SDF v2（44 字节头、16 字节 UUID、全局 sequence），原始帧独立提交到板载 HHW1GS60C-B3 裸扇区循环队列；UART2 仅发送丢旧保新的实时副本或收到 `AT+EXPORT=UART` 后的历史副本。

- UART2：上电默认 `115200` baud（可在 IDLE 持久化至 `3_000_000`）、8N1、无 RTS/CTS。
- STM32 启动默认实时配置：`AT+LIVESTREAM=UART`（冷启动默认）；实时副本只发送到 LIVESTREAM 选定的唯一目标。CDC 被选中但未连接时不自动回退 UART。非目标链路仍可收发 AT 控制响应。
- 不存在 `credit` 或其他软件流控命令；旧命令会被当作未知命令。
- UART 实时 DMA 启动失败、错误或中止只丢实时副本；SD 尾记录不回收，稍后可由 `EXPORT` 重发。
- `EXPORT=UART|CDC` 逐帧发送历史数据，整 chunk 的目标 DMA 完成后才回收；中断或掉电允许最多重复一个 chunk。
- CLI_RESPONSE 与 STATUS 不经过 SD，始终返回命令来源链路。
- `AT+EXPORT=UART` 只向 UART 发送历史帧，`AT+EXPORT=CDC` 只向 CDC 发送历史帧；`transport cdc|uart` 不再受支持。SD 是当前容量窗口内的权威存档，满卡覆盖最旧 chunk 并累计覆盖计数。

重要限制：UART DMA 成功只证明字节已离开 STM32 外设，不能证明 ESP32 已写入 PSRAM 或完成上行业务。因此本版本是“STM32 本地断线缓冲”，不是端到端确认交付协议。

## 2. 范围

### 2.1 必须实现

- UART RX 持续接收和错误统计。
- SDF1 V1/V2 任意分片解析、CRC 校验、magic 重同步和 sequence gap 统计；V2 传感器头固定 44 字节并校验 UUID。
- PSRAM 中明确所有权、永不覆盖未释放数据的环形缓冲。
- 将完整原始 SDF1 帧透明交给网络、本地存储或其他消费者。
- 对 RX 溢出、CRC storm、sequence 重置和消费者阻塞进行可观测恢复。
- 单元测试、故障注入和真实 3 Mbaud 压力测试。

### 2.2 不在本需求内

- 修改或重新编码 STM32 传感器 payload。
- 在 ESP32 上执行振动分析、姿态融合或绝对位置计算。
- 固定 Wi-Fi 上行协议；TCP、WebSocket、本地存储等均作为消费者实现。
- 把 UART DMA 完成描述成 ESP32 应用层确认。
- 声称尚未通过实物压力测试的路径可用于生产。

## 3. 物理与线缆合同

| STM32F407VET6 | ESP32 | Direction |
|---|---|---|
| PA2 / USART2_TX | UART_RX | STM32 -> ESP32 |
| PA3 / USART2_RX | UART_TX | ESP32 -> STM32 |
| GND | GND | Common reference |

双方使用兼容的 3.3 V UART 电平，不得接入 RS-232 电平。没有 RTS/CTS。ESP32 RX 驱动、DMA/环形缓冲和接收任务必须能持续处理 3 Mbaud 线速，并为调度抖动留余量。

完整帧格式只以 [PROTOCOL.md](./PROTOCOL.md) 为准。一次 UART read 可能包含半帧、多帧或垃圾前缀，不能当作帧边界。ESP32 不得修改 header、payload、sequence、timestamp 或 CRC；旁路指标必须与原始字节分离。

## 4. PSRAM 所有权

每个接收区间只能处于一个状态：

```text
UART RX -> RESERVED -> COMMITTED -> CONSUMING -> RELEASED
```

- `RESERVED`：RX 已取得写空间，消费者不可见。
- `COMMITTED`：数据已完整写入，消费者可见。
- `CONSUMING`：消费者持有只读视图，RX 不得覆盖。
- `RELEASED`：消费者确认处理完成，空间才重新可写。

禁止覆盖 `COMMITTED` 或 `CONSUMING` 数据。没有 STM32 端背压命令，所以本地空间不足时必须：

1. 继续服务 UART，尽可能准确统计实际丢失字节；
2. 标记当前解析会话不连续并重新搜索 `SDF1`；
3. 暴露溢出时间、字节数和当时水位；
4. 不得伪造完整帧或静默覆盖旧数据。

PSRAM 容量必须依据最大允许消费者阻塞时间和实测输入速率计算，不能把“有 PSRAM”本身当成不会溢出的证明。

## 5. 网关状态机

```text
BOOT -> UART_READY -> STREAMING
                      | CRC/line error -> RESYNCING
                      | PSRAM full     -> OVERFLOWED
                      | upstream fault -> DEGRADED
RESYNCING/OVERFLOWED/DEGRADED -> STREAMING after explicit recovery criteria
```

### 5.1 启动

1. 初始化并最小读写自检 PSRAM。
2. 初始化 3 Mbaud UART RX、解析器和指标。
3. 立即开始持续接收；不发送 credit，也不要求 STM32/ESP32 同步复位。
4. 第一个 CRC 正确的 SDF1 帧建立 sequence 基线。

ESP32 可发送 `AT+STATE?` 查询诊断；接收会话不依赖命令、ACK 或双方同步复位。

### 5.2 Streaming

- UART RX 优先级高于网络发送、日志格式化和文件写入。
- 热路径不动态分配大块内存，不逐字节打印日志。
- 解析器支持跨 PSRAM wrap 的双段视图或等价实现。
- CRC 错误从候选 magic 的下一个字节重新搜索。
- sequence gap 记录为健康事件，不阻塞后续有效帧交付。

### 5.3 恢复

- UART framing/overrun：清除外设错误，保留可证明完整的数据并重新同步解析器。
- CRC storm：限速记录，检查波特率、接地、电平和 RX 调度延迟。
- PSRAM 满：标记数据缺口，继续接收并在消费者释放空间后重新同步。
- STM32 重启：通过 sequence/timestamp 回退或 STATUS 变化建立新会话指标。
- ESP32 重启：直接重新初始化接收状态；STM32 可能正在发送，解析器必须能从任意字节位置恢复。

## 6. 建议接口

```c
gateway_rx_reservation_t gateway_ring_reserve(size_t requested);
void gateway_ring_commit(gateway_rx_reservation_t *reservation, size_t written);

gateway_read_view_t gateway_ring_acquire(void);
void gateway_ring_release(gateway_read_view_t *view, size_t consumed);

void sdf1_monitor_feed(const uint8_t *data, size_t length);
gateway_result_t stm32_control_send(const char *command);
gateway_state_snapshot_t gateway_status_snapshot(void);
```

消费者接口必须区分“读取了数据”和“已经安全提交处理”；只有后者可以释放 PSRAM 空间。

建议至少提供这些指标：

| Field | Type | Meaning |
|---|---|---|
| uart_rx_bytes | u64 | UART 接收总字节数 |
| uart_overrun_errors | u32 | RX 驱动溢出次数 |
| uart_line_errors | u32 | framing/parity 等错误 |
| valid_frames | u64 | CRC 正确帧数 |
| crc_errors | u64 | CRC 失败候选数 |
| sequence_gaps | u64 | 全局 sequence 缺口 |
| psram_capacity/used/peak | size_t | PSRAM 容量、水位和峰值 |
| dropped_bytes | u64 | 因本地容量或驱动错误丢失的字节 |
| recovery_count | u32 | 恢复次数 |
| last_error | enum | 最近错误原因 |

## 7. 验收条件

- [ ] UART 参数与 STM32 一致，并通过持续 3 Mbaud 输入测试。
- [ ] 任意分片、拼接、垃圾前缀和 PSRAM wrap 均能解析 SDF1。
- [ ] 输出的完整帧与 STM32 原始帧逐字节一致。
- [ ] 未释放数据永不被覆盖。
- [ ] ESP32 独立重启后可从任意 UART 字节位置恢复。
- [ ] STM32 独立重启后可建立新的 sequence/时间基线。
- [ ] PSRAM 满和 UART overrun 会产生明确、可查询的数据缺口指标。
- [ ] 网络消费者阻塞或断开不会破坏 RX 缓冲所有权。
- [ ] 使用 `test/golden/stream_v1_frames.bin` 验证协议边界。
- [ ] 与 Python `test/protocol.py` 对同一故障流给出一致的 CRC/sequence 结果。
- [ ] 连续运行至少 30 分钟，无未解释 sequence gap、缓冲越界或任务饿死。

如果产品要求“ESP32 已安全接收后 STM32 才删除记录”，必须新增带记录身份和会话语义的确认/窗口协议，并重新做掉电、重复确认和独立复位测试；当前固件不提供这个保证。

## 8. Revision History

| Date | Change |
|---|---|
| 2026-08-27 | 初始 credit 型网关需求 |
| 2026-09-01 | 改为 SD 优先、UART 无软件 credit；明确 DMA 完成不等于对端确认 |
