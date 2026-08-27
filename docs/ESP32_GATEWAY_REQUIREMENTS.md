# ESP32 通讯网关交接需求

> ESP32 通过无硬件流控的 3 Mbaud UART 接收 STM32 的 SDF1 数据流，以 PSRAM 提供可靠背压缓冲，并把原始帧透明交给后续网络或存储消费者。

**Module:** Sensor Acquisition / ESP32 Gateway

**Status:** Planned

**Started:** —

**Completed:** —

**Issue:** —

---

## 1. User Story

**As a** ESP32 固件开发者，

**I want** 获得明确的 STM32 UART、SDF1、credit、缓冲所有权和恢复契约，

**So that** 可以独立实现并验证通讯模组，而不需要猜测 STM32 的实时行为。

---

## 2. Overview

STM32 是传感器采集和 SDF1 编码的权威端。ESP32 是传输网关，不重新解释或改写业务数据。ESP32 从 UART2 接收任意分片的字节流，写入 PSRAM 环形缓冲，验证帧边界、CRC 和 sequence 以生成健康指标，然后由一个或多个消费者读取完整的原始 SDF1 帧。

当前联调阶段仅使用 USB CDC 与上位机。本文定义下一阶段 ESP32 实现及验收合同，不表示 UART/ESP32 硬件路径已经通过验证。

### 2.1 Basic Scenario

1. ESP32 初始化 UART、PSRAM 环形缓冲和 SDF1 流式解析器。
2. ESP32 建立一个有限 credit 窗口，再请求 STM32 将采集数据切换到 UART。
3. STM32 仅在 credit 足够容纳完整帧时启动 UART DMA。
4. ESP32 写入未读数据不被覆盖的 PSRAM 缓冲，同时统计 CRC、sequence 和缓冲水位。
5. 消费者提交已处理字节后，ESP32 才把对应真实释放空间重新发放为 credit。
6. 发生重启、解析错误或消费者阻塞时，状态机进入可诊断的恢复状态，不伪造可用空间。

---

## 3. Scope

### 3.1 Included

- USART2：3,000,000 baud、8N1、TX/RX、无 RTS/CTS。
- SDF1 V1 任意分片接收、重同步、CRC 和 sequence 监控。
- PSRAM 单生产者/单消费者或等价的显式所有权环形缓冲。
- 基于真实可写空间的累计字节 credit。
- STM32 `transport uart|cdc` 控制和链路恢复。
- 独立的接收、解析、缓冲、消费者和健康指标接口。
- 单元测试、故障注入和硬件压力测试。

### 3.2 Excluded

- 修改 SDF1 传感器 payload 或重新编码 STM32 原帧。
- 在本需求中固定 Wi-Fi 上行协议。TCP、WebSocket、USB 或存储均实现为消费者。
- 在 ESP32 上计算振动分析、姿态融合或绝对位置。
- 在当前 CDC-only 测试阶段宣称 ESP32 路径已经可用于生产。

---

## 4. Physical and Wire Contract

### 4.1 Wiring

| STM32F407 | ESP32 | Direction |
|---|---|---|
| PA2 / USART2_TX | UART_RX | STM32 -> ESP32 |
| PA3 / USART2_RX | UART_TX | ESP32 -> STM32 |
| GND | GND | Common reference |

双方必须使用兼容的 3.3 V UART 电平。不得接入 RS-232 电平。没有 RTS/CTS，所有背压均由应用层 credit 完成。

### 4.2 UART

- Baud rate: `3_000_000`
- Data bits: `8`
- Parity: none
- Stop bits: `1`
- Hardware flow control: none
- STM32 oversampling: `8`
- ESP32 RX 缓冲和任务优先级必须能持续接收约 187 KiB/s 的 IIS3DWB 原始流，并保留突发余量。

### 4.3 SDF1

完整帧格式、消息类型、payload 换算、CRC 和重同步算法只以 [PROTOCOL.md](./PROTOCOL.md) 为准。ESP32 实现不得把一次 UART read 当作一帧，也不得在转发时修改 header、payload、sequence、timestamp 或 CRC。

允许 ESP32 生成独立的旁路元数据，例如：

```text
gateway_rx_time_us
frame_offset
frame_length
crc_ok
sequence
sequence_gap
psram_used_bytes
```

旁路元数据不能插入原始 SDF1 字节流。

---

## 5. Buffer Ownership and Backpressure

### 5.1 Required Ownership Model

每个已接收字节只能处于一个状态：

```text
UART DMA/RX -> RESERVED -> COMMITTED -> CONSUMING -> RELEASED
```

- `RESERVED`：生产者已获得连续或分段写空间，消费者不可见。
- `COMMITTED`：完整写入，消费者可见。
- `CONSUMING`：消费者持有只读区间，生产者不得覆盖。
- `RELEASED`：消费者提交处理完成，空间重新可写。

禁止覆盖 `COMMITTED` 或 `CONSUMING` 数据。空间不足时停止新增 credit，并记录背压状态；不得通过覆盖旧数据制造“可用空间”。

### 5.2 Credit Accounting

STM32 当前命令为：

```text
credit <1..1048576>\r\n
```

credit 表示 ESP32 承诺还能可靠接收的字节数：

```text
outstanding_credit
  = total_credit_granted
  - bytes_received_against_credit
```

必须满足：

```text
outstanding_credit <= safe_writable_capacity
```

其中 `safe_writable_capacity` 需要扣除 UART 驱动未提交字节、解析保留区、消费者尚未释放区和安全余量。只有消费者执行 `release(n)` 后，`n` 才有资格进入下一批 credit。

建议首版：

- PSRAM 数据环容量至少 1 MiB，具体值由目标板 PSRAM 余量决定。
- 初始窗口不超过实际环容量的 50%，且不超过 STM32 上限 1 MiB。
- credit 聚合粒度从 16 KiB 开始实测，避免逐帧控制开销。
- 保留至少 `2 * 3609` 字节不可发放安全余量。
- 所有计数使用至少 64 位累计值；与 STM32 交互的单次 credit 限制为 32 位协议范围。

### 5.3 Independent Reset Gap

现有 STM32 V1 只有“累加 credit”，没有撤销或替换剩余 credit 的命令。当 ESP32 独立复位而 STM32 未复位时，STM32 可能仍持有旧 credit；ESP32 无法证明旧 credit 与新 PSRAM 状态一致。

因此，UART 生产验收前必须在 STM32 控制面增加并测试以下等价能力之一：

```text
credit reset
```

或一个能够在发送帧边界原子替换剩余 credit 的版本化命令。推荐 `credit reset`：仅 UART 控制入口可用，Transport 任务在当前帧结束或中止后把剩余 credit 清零，再返回成功响应。ESP32 收到成功响应后才清空本地旧会话并发放新窗口。

在该能力落地之前：

- ESP32 开发可使用 STM32 与 ESP32 同步复位进行实验。
- 不得把 ESP32 独立重启恢复列为已通过。
- 不得在重启后直接重复发放“整个空闲 PSRAM”作为新 credit。

---

## 6. Gateway State Machine

```text
BOOT
  -> UART_READY
  -> QUIESCE_STM32
  -> RESET_SESSION
  -> GRANT_WINDOW
  -> REQUEST_UART
  -> STREAMING
       | consumer slow / low free space -> BACKPRESSURED
       | CRC storm / UART error         -> RECOVERING
       | user requests debug            -> REQUEST_CDC
  -> STREAMING or SAFE_CDC
```

### 6.1 Boot and Session Start

1. 初始化 PSRAM 并运行内存自检或最小读写验证。
2. 初始化 UART RX 和控制 TX；先不发放 credit。
3. 请求 STM32 暂停 UART 数据路由：`transport cdc`。
4. 执行 `credit reset`；等待命令来源链路上的成功响应。
5. 清空本地解析器、环形缓冲和会话级 sequence 基线。
6. 依据真实安全空间发送有限 `credit N`。
7. 发送 `transport uart`。
8. 收到有效 SDF1 帧后进入 `STREAMING`。

控制命令与响应是会话建立的一部分，不能用固定延时替代确认。超时进入 `SAFE_CDC` 并暴露错误原因。

### 6.2 Streaming

- UART RX 优先级必须高于网络发送、日志格式化和文件写入。
- 热路径禁止动态分配大块内存、浮点格式化和逐字节日志。
- 解析器可以跨 PSRAM wrap 边界工作，或使用不改变原始数据的双段视图。
- CRC 错误从候选 magic 后一个字节重搜；不得按未验证长度盲跳。
- sequence 缺口只记录，不阻止后续有效帧交付。

### 6.3 Backpressured

- 停止发放新 credit。
- 继续接收已经授权且在途的数据。
- 当消费者释放空间并超过聚合阈值后恢复发放。
- PSRAM 接近满不是重启理由；必须有高水位、持续时间和最大占用指标。

### 6.4 Recovering

以下条件进入恢复：UART 驱动错误、连续 CRC 错误超过阈值、缓冲所有权不变量失败、STM32 sequence 异常重置或控制超时。

恢复顺序为：请求 CDC -> credit reset -> 清空本地会话 -> 有限 credit -> 请求 UART。无法恢复时留在 `SAFE_CDC`，不得无限快速重试。

---

## 7. Public Software Interfaces

ESP32 内部实现语言和 RTOS 组件可自行选择，但至少提供下列等价边界：

```c
gateway_rx_reservation_t gateway_ring_reserve(size_t requested);
void gateway_ring_commit(gateway_rx_reservation_t *reservation, size_t written);

gateway_read_view_t gateway_ring_acquire(void);
void gateway_ring_release(gateway_read_view_t *view, size_t consumed);

void sdf1_monitor_feed(const uint8_t *data, size_t length);
gateway_credit_update_t gateway_credit_on_release(size_t released);

gateway_result_t stm32_control_send(const char *command);
gateway_state_snapshot_t gateway_status_snapshot(void);
```

消费者接口必须区分“读取了数据”和“已经安全提交处理”；只有后者释放 PSRAM 和生成 credit。

---

## 8. Data Model

### 8.1 Gateway Status Snapshot

| Field | Type | Description |
|---|---|---|
| state | enum | 当前网关状态 |
| session_id | u32/u64 | 每次成功重建会话递增 |
| uart_rx_bytes | u64 | UART 接收总字节数 |
| valid_frames | u64 | CRC 正确的 SDF1 帧数 |
| crc_errors | u64 | CRC 失败候选数 |
| sequence_gaps | u64 | STM32 全局序号缺口数 |
| psram_capacity | size_t | 数据环总容量 |
| psram_used | size_t | 当前占用 |
| psram_peak | size_t | 会话峰值占用 |
| outstanding_credit | u32 | 估算尚未消耗的授权字节 |
| credit_granted | u64 | 累计发放 credit |
| consumer_released | u64 | 消费者累计释放字节 |
| recovery_count | u32 | 恢复尝试次数 |
| last_error | enum | 最近错误原因 |

---

## 9. Acceptance Criteria

### 9.1 Core Functionality

- [ ] UART 参数与 STM32 一致，并通过持续吞吐测试。
- [ ] 任意分片、拼接、垃圾前缀和 PSRAM wrap 均能解析 SDF1。
- [ ] 转发输出与 STM32 原始帧逐字节一致。
- [ ] CRC、sequence 和缓冲水位指标可查询。
- [ ] 未释放数据永不被覆盖。
- [ ] credit 只来源于经过安全余量修正的真实空间。
- [ ] 消费者暂停时 credit 最终耗尽，STM32 不再启动新 UART 数据帧。
- [ ] 恢复消费后链路无需重启即可继续。

### 9.2 Recovery and Edge Cases

- [ ] ESP32 独立重启通过 `credit reset` 建立新会话，不重复授权旧空间。
- [ ] STM32 独立重启后 ESP32 能识别 sequence/状态变化并重建会话。
- [ ] CRC 错误、UART 错码和随机垃圾不会让解析器永久失步。
- [ ] 网络消费者阻塞、断开或变慢不会破坏 UART RX 所有权。
- [ ] PSRAM 满、控制超时和恢复失败进入可诊断安全状态。
- [ ] 连续运行至少 30 分钟，无所有权错误、未解释 sequence gap 或缓冲越界。

### 9.3 Interoperability

- [ ] 使用 `test/golden/stream_v1_frames.bin` 验证编码边界。
- [ ] ESP32 指标与 Python `test/protocol.py` 对同一故障流给出一致 CRC/sequence 结果。
- [ ] CDC 与 ESP32 UART 获得的原始 SDF1 数据可由同一主机解析器读取。

---

## 10. Technical Notes

### Approach

推荐把 UART RX、PSRAM ring、SDF1 monitor、credit controller 和上行 consumer 分成独立模块。接收热路径只做固定成本的数据搬运和通知；CRC/帧监控可以在第二个高优先级任务中处理，但不能阻塞 RX 提交。

### Dependencies

- STM32 [PROTOCOL.md](./PROTOCOL.md) 和 golden frames。
- 具有 PSRAM 的目标 ESP32 板卡。
- ESP-IDF UART、内存和任务调度组件，或功能等价实现。
- 尚未实现的 STM32 `credit reset` 控制语义。

### Performance Considerations

- 以至少 2 倍当前有效流量进行软件输入压力测试。
- 禁止在 UART RX 热路径打印逐帧日志。
- 网络上行必须从消费者边界读取，不能持有 ring view 跨越不可控阻塞。
- 高水位策略以字节容量和可证明所有权为准，不按“帧数估计空间”。

### Standards Checklist

- [ ] 测试先覆盖 ring wrap、所有权和 credit 不变量。
- [ ] 模块只通过公开接口协作，无共享可变指针泄漏。
- [ ] 所有计数溢出策略明确。
- [ ] 输入长度、命令响应和数值上限均校验。
- [ ] 无硬编码网络凭据或密钥。
- [ ] 故障日志限速且不阻塞 RX。
- [ ] 本文验收项完成后更新状态和路线图。

---

## 11. Open Questions

- [ ] **Open:** ESP32 的第一种上行消费者选择 TCP、WebSocket、USB 还是本地存储；该选择不改变 UART/SDF1/credit 合同。
- [x] **Resolved:** ESP32 不做姿态或振动业务计算，只透明转发并生成链路指标。
- [x] **Resolved:** 当前阶段上位机只通过 CDC 验证，UART/ESP32 后移。
- [x] **Resolved:** 独立重启必须引入显式 credit 会话重置，不能用重复累加代替。

---

## 12. Related Features

- [SDF1 V1 通讯协议](./PROTOCOL.md)
- [后续实现路线图](./ROADMAP.md)
- [PyQt 采集上位机设计](./plans/2026-08-27-sensor-host-application-design.md)

---

## 13. Revision History

| Date | Author | Change |
|---|---|---|
| 2026-08-27 | Codex | 初始交接需求，记录 CDC-only 当前阶段和 credit reset 前置依赖 |
