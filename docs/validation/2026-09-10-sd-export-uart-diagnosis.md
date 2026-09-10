# SD 卡历史数据上传链路诊断

日期：2026-09-10

上位机仓库：`D:\Codes\SensorHost`

上位机分支：`feature/sd-archive-replay`

上位机基线提交：`f964bb7`

固件仓库：`D:\Codes\STM32\STM32407ZG_JY61PL_II3DWB_UART_V2`

固件分支/提交：`master` / `3055ae2`（相对远端 ahead 1，当前提交仅包含设计文档）

## 1. 结论摘要

`AT+EXPORT=UART` 命令本身是通的：上位机能够把命令送到固件，固件接受命令后也能够通过原控制链返回 `EXPORT_ABORTED`。失败发生在固件尝试发送第一帧 SD 历史数据时，而不是发生在上位机创建文件、解析 SDF1 或写盘阶段。

当前最高置信度根因是：固件 UART 启动函数把 `HAL_BUSY` 和永久错误都映射为 `TRANSPORT_START_FAIL`；UART 导出路径收到该结果后立即发布失败结果，Storage 状态机随即结束导出并返回 `EXPORT_ABORTED`。同一个固件已经为 CDC 的 BUSY 情况实现了“保留原帧并重试”，但 UART 没有对称处理。

现场计数同时表明 UART 发送状态长期存在异常：`transport_drops=36872`、`cdc_errors=0`、`uart_dma_errors=3`。按照当前固件计数定义，前两项意味着 36,872 次 transport start failure 均来自 UART；`uart_dma_errors` 则是 USART2 transport、JY61PL UART 和控制 UART RX 错误的聚合值，不能仅凭该字段归属到 export TX。大量已确认的 UART start failure 已足以解释为什么导出首帧会稳定地快速失败。

故障归属判断：

| 环节 | 判断 | 置信度 |
|---|---|---:|
| 上位机发出导出命令 | 正常 | 高 |
| 固件解析并接受导出命令 | 正常 | 高 |
| 固件从 SD 识别出非空历史 | 正常，SD 状态报告 30,463 chunks | 高 |
| 固件 UART 历史帧发送 | 故障点 | 高 |
| ESP32/Wi-Fi 转发 | 不是当前立即 ABORT 的首要原因 | 中高 |
| 上位机 SDF1 解析与写盘 | 已有测试覆盖，未见故障证据 | 高 |

由于生产 SD 当前满载，且导出具有移动/回收语义，本次没有再次执行破坏性的实机导出。因而“HAL_BUSY 未重试”属于由现场计数、时间特征和源码控制流共同支持的高置信度诊断，最终确认仍需修复固件后用可牺牲数据做一次端到端验证。

## 2. 现场现象与证据

### 2.1 上位机导出记录

本地目录 `C:\Users\44575\AppData\Local\SensorHost\exports` 中存在多批失败记录。抽样包括：

| UTC 开始时间 | 结束时间 | 耗时 | 结果 | 写入字节 |
|---|---|---:|---|---:|
| 2026-09-10 06:52:09.459772 | 06:52:09.569344 | 约 110 ms | aborted | 0 |
| 2026-09-10 06:52:09.574362 | 06:52:09.709843 | 约 135 ms | aborted | 0 |
| 2026-09-10 05:52:21.788106 | 05:52:21.884232 | 约 96 ms | aborted | 0 |
| 2026-09-10 05:52:21.886239 | 05:52:21.979046 | 约 93 ms | aborted | 0 |

所有 sidecar 均具有以下共同特征：

- `status` 为 `aborted`；
- `bytes_written` 为 `0`；
- `failure` 为 `null`，说明本地 recorder 线程没有写盘异常；
- `export_chunks` 与 `export_frames` 为 `null`，说明没有收到正常的 `EXPORT_END` 统计；
- 每次尝试在约 0.1 秒内得到明确终止状态，不符合主机超时、磁盘阻塞或大文件传输中途失败的特征。

### 2.2 非破坏性实机状态查询

通过 STM32 CDC `COM19` 发送一次 `AT+STATE?`，收到完整、CRC 正确的 CLI_RESPONSE：

```text
+STATE:IDLE
+BAUD:460800
+SD:USED=124776448,CAPACITY=124776448,PENDING_FRAMES=126794,
RETAINED_CHUNKS=30463,RETAINED_FRAMES=126794,
OVERWRITTEN_CHUNKS=211949,OVERWRITTEN_FRAMES=739731,
READY=1,FORMAT_REQUIRED=0
+EXPORT:TARGET=NONE,CHUNK=0,FRAME=0
+LIVE:TARGET=UART,DROPS_IIS=265435,DROPS_JY=2969,
LAST_ROUTED_SEQUENCE=1638665,LAST_COMPLETED_SEQUENCE=1638661
+DIAG:POOL_FAIL=0,INGRESS_DROP=0,NOSTORE_DROP=167676,
POOL_MIN=6,INGRESS_PEAK=4,SD_STALL_MS=51,
CDC_LIVE=0,CDC_CTRL=0,CDC_EXPORT=0
+STOP_REASON:NONE
OK
```

该结果证明：

- 固件处于允许导出的 `IDLE`；
- SD 已就绪且不是空存档；
- 固件当前没有残留的活动导出；
- CDC 控制请求与 SDF1 CLI_RESPONSE 返回链路正常；
- UART 实时目标的 routed/completed sequence 正在推进，UART 不是完全失效，而是存在大量瞬态启动失败或少量 DMA 失败。

随后通过 CDC 发送无副作用的 `status` 查询，得到二进制 STATUS v1：

```text
transport_drops = 36872
uart_dma_errors = 3
cdc_errors = 0
command_errors = 0
source_drops = 0
```

查询过程的 SDF1 parser 统计为：`crc_errors=0`、`header_errors=0`、`length_errors=0`、`payload_errors=0`。

## 3. 完整数据流追踪

### 3.1 上位机侧

1. `ArchiveView` 选中设备后发出 `export_requested(node_id)`。
2. `AppController.start_export_for()` 检查 SD ready、设备状态为 IDLE，并根据 transport 类型选择导出目标：CDC 连接使用 `CDC`，Wi-Fi 节点使用 `UART`。
3. 上位机先创建并挂接 `RawSessionRecorder`，再发送 `AT+EXPORT=UART`。因此不会出现“首帧先到、recorder 后挂接”的窗口。
4. `AcquisitionController._handle_frame()` 只把带 `ARCHIVE_EXPORT` 标志的完整原始帧交给 archive recorder；普通实时帧不会误写入导出文件。
5. CLI_RESPONSE 中的 `EXPORT_END`、`EXPORT_EMPTY` 或 `EXPORT_ABORTED` 更新 `FirmwareControlState`。控制器随后停止 recorder、写 sidecar 并通知 UI 刷新。

上位机已有端到端自动测试覆盖：发送 `AT+EXPORT=UART`、接收两帧带 `ARCHIVE_EXPORT` 的 SDF1、接收 `EXPORT_END`、写入本地库、打开并回放。该测试通过，说明只要固件真的返回 archive frame，上位机保存链路可以工作。

### 3.2 固件控制与存储侧

1. `control_parser.c` 接受 `AT+EXPORT`、`AT+EXPORT=UART` 和 `AT+EXPORT=CDC`。
2. `control.c:start_export()` 仅在 IDLE 下进入 EXPORT，并调用 `StoragePipeline_StartExport()`。
3. 固件通过命令来源端返回 `EXPORT_BEGIN:UART` 和 `OK`。
4. `storage_pipeline.c:load_export_chunk()` 使用 `SdSpool_PeekChunk()` 读取最旧 chunk。
5. `dispatch_one_frame()` 从 chunk 取出下一帧，在 RAM 副本中设置 `ARCHIVE_EXPORT` 并重算 CRC，然后调用 `Transport_QueueExportFrame()`。
6. Transport task 取出该帧，并调用 `TransportAdapter_SubmitExport()`。
7. UART backend 最终调用 `HAL_UART_Transmit_DMA()`。
8. 只有 transport 发布 `success=true` 后 Storage 才推进 frame index；整 chunk 全部成功后才回收该 chunk。
9. transport 发布 `success=false` 时，`StoragePipelineCore_OnTransmitResult()` 返回 `STORAGE_PIPELINE_ABORT_EXPORT`，控制任务最终回复 `EXPORT_ABORTED`。

现场得到明确 `EXPORT_ABORTED` 而不是 `ERROR:STATE`、`EXPORT_EMPTY` 或主机 watchdog 的 `STALLED`，因此命令解析、状态门禁和“SD 是否为空”均不是当前失败点。

## 4. 最可能的固件缺陷

### 4.1 UART 将 HAL_BUSY 当作永久失败

当前 `uart_start()` 的逻辑等价于：

```c
status = HAL_UART_Transmit_DMA(...);
if (status != HAL_OK) {
    return TRANSPORT_START_FAIL;
}
return TRANSPORT_START_OK;
```

这会把以下状态合并：

- `HAL_BUSY`：HAL/外设尚未从上一笔发送切回 ready，通常应稍后重试；
- `HAL_ERROR`：真正的启动错误；
- `HAL_TIMEOUT`：启动过程超时。

CDC backend 已经把 `USBD_BUSY` 映射为 `TRANSPORT_START_BUSY`。CDC export 遇到 BUSY 时会释放软件 reservation、不发布失败结果，并把完全相同的帧放回队列重试。UART 没有这条分支：任何非 OK 状态都会调用 `TransportCore_OnUartStartFailed()`，然后 `publish_result(false)`。对实时流而言这只表现为丢一帧；对 archive export 而言，一次瞬态 BUSY 就会中止整次导出。

现场 `transport_drops=36872` 且 `cdc_errors=0` 与这个缺陷一致：固件已经累计大量 UART start failure。导出每次都在首帧、约 0.1 秒内 abort，也与首帧遇到瞬态 BUSY 后立即走永久失败路径一致。

### 4.2 次要风险：RX/TX DMA 错误归属不够精确

当前 `HAL_UART_ErrorCallback()` 对 USART2 的判断是：只要 `huart->ErrorCode` 含 `HAL_UART_ERROR_DMA` 且此刻 `uart_tx_active=true`，就调用 `Transport_OnUartErrorFromIsr()`。USART2 同时使用 RX DMA1 Stream5 和 TX DMA1 Stream6；该判断没有确认报错的 DMA handle/方向。

因此存在一种次要可能：RX DMA 在长时间 UART TX 期间报错，被误归类为 TX DMA error，进而中止 export。现场聚合字段 `uart_dma_errors=3` 只能证明 USART2 transport、JY61PL UART 或控制 UART RX 三类来源合计发生过三次错误；它不能证明三次都走入 export TX 错误路径。现有遥测没有保存最后一次 HAL status、DMA stream 或 DMA error code，无法仅凭当前计数区分真实 TX DMA 错误、RX DMA 误归类或其他 UART 来源。

这不是解释 36,872 次 start failure 的首要原因，但修复时应一并增加方向明确的错误诊断。

### 4.3 为什么 ESP32/Wi-Fi 网关不是当前首要原因

ESP32 仍可能在高速持续传输中发生缓存溢出、分包或转发丢失，但这些问题发生在 STM32 UART DMA 已经成功启动之后。USART2 没有 RTS/CTS，接收端是否及时消费不会直接令 `HAL_UART_Transmit_DMA()` 返回 BUSY/ERROR。

如果只是 ESP32 丢弃已发送字节，STM32 通常会继续得到 TX complete、推进导出并最终发 `EXPORT_END`；上位机侧更可能看到解析错误、sequence 缺口或固件声称完成但文件不完整，而不是约 0.1 秒内收到固件主动返回的 `EXPORT_ABORTED`。

因此网关仍是修复后的端到端验证对象，但不是当前立即 abort 的第一嫌疑。

## 5. 建议修复方案

固件修改建议限定在 transport 层，不改变 SD 所有权和回收语义：

1. `uart_start()` 将 `HAL_BUSY` 映射为 `TRANSPORT_START_BUSY`；只把 `HAL_ERROR`/`HAL_TIMEOUT` 映射为 `TRANSPORT_START_FAIL`。
2. `TransportAdapter_SubmitExport()` 为 UART 增加与 CDC 对称的 BUSY 分支：
   - 释放 UART software reservation/owner；
   - 不增加永久失败计数；
   - 不发布 `StorageTransmitResult(success=false)`；
   - 设置 `retry=true`，由 `try_export()` 把原帧重新排队。
3. 明确处理“重新入队也失败”的异常路径，不能静默丢帧并让 Storage 永久保持 `transmit_in_flight`。
4. 为 UART start 结果增加分项遥测：`busy`、`error`、`timeout`，至少保存最近一次 HAL status。
5. 将 USART2 RX DMA 与 TX DMA 错误分开计数；只有确认 TX DMA 出错时才中止 export。
6. 保持以下不变量：同一时刻最多一帧 archive in flight；BUSY 重试必须使用相同 `chunk_id/frame_index/data`；只有成功完成整 chunk 才能回收。

## 6. 建议验证流程

### 6.1 主机单元测试

在 `test/host/test_transport_adapter.c` 增加：

- UART export 首次 `TRANSPORT_START_BUSY`：不发布失败结果，原帧要求重试；
- BUSY 后成功：只发布一次 `success=true`；
- UART `TRANSPORT_START_FAIL`：仍发布一次 `success=false`；
- UART DMA error：仍中止当前 export；
- BUSY 重排队失败：进入明确错误/终止路径，不悬挂 Storage 状态。

运行固件仓库标准门禁：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\test_stage1.ps1
```

### 6.2 构建与烧录前检查

1. 清洁构建 Debug 和 Release。
2. 检查 linker map，确认 export frame 位于 DMA 可访问的 SRAM。当前 Release map 中 `export_frame` 位于 `0x20011a08`，不是 DMA 不可访问的 CCMRAM。
3. 记录 ELF SHA-256。
4. 烧录前读取并保存现有 Flash；烧录后执行 verify。

### 6.3 实机端到端验证

当前生产 SD 已满并含 126,794 retained frames，不应直接用于试错。推荐使用可牺牲 SD 卡或经用户明确允许清空后的测试卡：

1. `AT+SDCLEAR=CONFIRM`，确认 retained/used 归零。
2. 采集一小段已知数据，`AT+STOP` 后记录 retained chunks/frames/bytes。
3. 记录导出前 STATUS 中的 UART busy/start error/DMA error 计数。
4. 通过实际 Wi-Fi 节点发起 `AT+EXPORT=UART`。
5. 上位机必须观察到：
   - `EXPORT_BEGIN:UART`；
   - 至少一帧带 `ARCHIVE_EXPORT` 的合法 SDF1；
   - 本地文件 `bytes_written > 0`；
   - 最终 `EXPORT_END:CHUNKS=n,FRAMES=n`；
   - `n` 与导出前 retained 统计一致。
6. 对本地文件执行完整 parser/CRC/UUID/sequence 检查并打开回放。
7. 再次查询 SD，确认只有已经完整发送的 chunk 被回收。
8. 单独做一次中断测试：在未完成一个 chunk 时取消，确认该 chunk 保留；重新导出允许重复但不得缺帧。

### 6.4 若修复后仍失败

按以下边界逐层加证据，不再依靠单一 `EXPORT_ABORTED` 文本：

```text
Storage PeekChunk
  -> MarkArchiveExport + CRC
  -> Transport data queue put
  -> UART HAL start result
  -> TX DMA complete/error + stream id/error code
  -> ESP32 UART RX byte/frame counters
  -> TCP forwarded byte/frame counters
  -> SensorHost parser archive frame count
  -> recorder accepted/written byte count
```

每层至少记录进入数量、成功数量、失败原因与最后一个 `(chunk_id, frame_index, sequence)`。这样可以确定字节第一次消失在哪个边界。

## 7. 本次未执行的操作

- 未修改固件源码；
- 未重新构建或烧录固件；
- 未发送新的 `AT+EXPORT`；
- 未清空或回收生产 SD 中的任何 chunk；
- 未修改 ESP32 网关。

此外，本次没有从 MCU Flash 读回整镜像并与仓库 ELF 比对，因此不能把当前板载二进制的精确 Git 提交身份视为已验证事实。

这些限制用于保护当前满载 SD 数据，并区分“源码静态诊断”与“修复后实机确认”。
