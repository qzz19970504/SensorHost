# 实时绘图卡顿 bug 报告（2026-09-08）

## 结论

**定位结果：这是固件侧的实时数据管线问题，置信度高。** 卡顿在数据到达上位机之前已经发生；Qt 绘图和本轮 UI 修改不是主因。直接触发点是同步 SD 写入阻塞，随后存储队列形成背压，共享帧池耗尽，采集帧被丢弃或成批延迟送出，最终在曲线上表现为约 0.2～0.35 秒的停顿。

板载 SD 的物理介质状态可能放大写延迟，但不是当前证据能够单独确认的根因。即使逻辑清空归档，卡顿和帧池耗尽仍可稳定复现，因此“SD 逻辑空间满”不是必要条件，也不能只靠清空数据解决。

## 影响

- IIS3DWB 实时曲线周期性停住后跳动，视觉上像绘图线程卡顿。
- 15 秒内 `POOL_FAIL` 增加约 1500 次，说明固件在采集端持续丢帧。
- 关闭 CDC 实时输出、只保留 UART 目标时仍出现相同数量级的 `POOL_FAIL`，说明主机是否消费 CDC 数据不决定该问题。
- SD 元数据异常或落后时，固件会扫描约 124.8 MB 的整个逻辑环形区；扫描任务优先级高于控制任务且循环不主动让出 CPU，期间 COM6 虽已枚举但 AT 命令长期无响应。

## 测试环境

- 上位机仓库：`D:/Codes/SensorHost`，`master` / `eaa91e9`
- 对比上位机：`aeacedf`（本轮 UI 美化前版本，并非用户所说的更早已知正常版本）
- 固件仓库：`D:/Codes/STM32/STM32407ZG_JY61PL_II3DWB_UART_V2`，基线 `4406619`
- 设备：COM6，STM32F405/F407，ST-Link `37FF71064E573436947D1143`
- 设备 UUID：`49005000-0e50-8731-9432-39203731a4f8`
- 原始板载 Flash 已完整备份：`build/stutter-investigation/firmware/original-flash.bin`

## 复现步骤

1. 让设备处于 IDLE，连接 COM6。
2. 选择 CDC 为实时目标并开始采集，不开启录制。
3. 直接从串口读取协议帧 15 秒，记录完整帧到达时间与固件状态计数器。
4. 重复测试，但把实时目标切到 UART，使 CDC 只用于测试前后的控制查询。
5. 在 IDLE 下执行 `AT+SDCLEAR=CONFIRM`，确认 `USED`、`RETAINED_FRAMES` 和 `OVERWRITTEN` 清零，再重复步骤 2～4。

预期：实时流保持稳定，帧池不持续耗尽。

实际：无 GUI 时仍有 200～350 ms 到达间隔，`POOL_FAIL` 约每秒增加 100 次。

## 测量结果

| 场景 | 到达间隔 p95 | 最大间隔 | >100 ms 次数 | `POOL_FAIL` / 15 s | 送达样本/秒 |
|---|---:|---:|---:|---:|---:|
| 原始逻辑满环，裸 CDC | 322.5 ms | 346.6 ms | 34 | +1600 | 3755 |
| SD 逻辑清空后，裸 CDC | 204.5 ms | 276.6 ms | 47 | +1523 | 4926 |
| 原始逻辑满环，UART 实时/CDC 无实时流 | — | — | — | +1575 | — |
| SD 逻辑清空后，UART 实时/CDC 无实时流 | — | — | — | +1486 | — |

协议解析耗时 p95 为 2.48 ms、最大 6.47 ms，远小于 200～350 ms 的数据空洞。CRC 错误为 0。

GUI 对比结果：

| 上位机 | 更新回调 p95 / max | 快照间隔 p95 / max |
|---|---:|---:|
| 当前 `eaa91e9` | 1.17 / 2.11 ms | 67.51 / 81.95 ms |
| UI 修改前 `aeacedf` | 0.81 / 2.57 ms | 64.65 / 72.67 ms |

两版 GUI 的回调都没有出现与裸串口数据空洞相当的 200～350 ms 阻塞；差异不足以解释现象。

## 固件插桩结果

在诊断分支 `codex/sd-stutter-diagnostics` 中，仅给 SD 读、写和 wait-ready 增加累计计时，使用 Debug 配置刷入同一块板。15 秒采集结果：

| SD 阶段 | 调用次数 | 数据量 | 累计耗时 | 单次最大 | >=20 ms |
|---|---:|---:|---:|---:|---:|
| 读 | 16 | 15,360 B | 33 ms | 10 ms | 0 |
| 写 | 58 | 759,808 B | 1,039 ms | 35 ms | 40 |
| wait-ready | 58 | — | 40 ms | 10 ms | 0 |

同一窗口内裸 CDC 到达间隔 p95 为 247.7 ms、最大 253.2 ms，出现 40 次大于 100 ms 的空洞。58 次写中有 40 次达到或超过 20 ms；主要阻塞发生在同步 `HAL_SD_WriteBlocks()` 内，而不是随后轮询卡状态的 wait-ready 阶段。

## 根因链路

1. `app/Storage/sd_card.c` 使用同步 `HAL_SD_ReadBlocks()` / `HAL_SD_WriteBlocks()`。
2. `app/Storage/storage_pipeline.c` 的 SD 写入与存储入口队列消费位于同一任务；一次写可阻塞 20～35 ms，批量写、检查点和调度叠加后会更长。
3. `StoragePipeline_SubmitFrame()` 对深度 8 的队列使用 `osWaitForever`。
4. `app/Pipeline/frame_router.c` 在同一个路由调用中先投递实时数据，再同步进入存储 sink；存储阻塞会反向卡住路由任务。
5. 采集、实时输出和存储共享仅 12 个帧缓冲。路由/存储停滞时缓冲很快耗尽，`POOL_FAIL` 持续上升。
6. 上位机只能收到固件最终送出的帧，所以这些源端停顿直接表现为绘图卡顿。

这是由实测支持的主链路。板载 SD 的 FTL/垃圾回收、当前 1-bit 12 MHz SDIO 配置以及 Debug `-O0` 会影响阻塞幅度，但不改变“同步存储背压侵入实时链路”的设计缺陷。

## 额外发现：启动全盘扫描饿死控制任务

刷回基线后，COM6 可枚举但 AT 命令长时间无响应。SWD 读取显示 MCU 没有 HardFault，PC 在 `HAL_SD_ReadBlocks()` 与 `StreamProtocol_Crc32()` 之间运行，调用栈位于 `SdChunkCore_Open()` / `SdSpool_Init()` 的恢复路径。

`recover_full_scan()` 会逐个读取约 30,463 个 4 KiB chunk，即约 124.8 MB。`StorageTask` 是 `osPriorityAboveNormal`，`ControlTask` 是 `osPriorityNormal`，扫描循环没有 `osDelay()` 或 `taskYIELD()`。因此扫描期间较低优先级的控制任务可能长期得不到运行机会。这解释了“USB 已连接但所有 AT 命令超时”，也是独立的固件问题。

## 建议修复顺序

1. **隔离实时链路与存储背压。** `FrameRouter` 向存储提交时使用有界、非阻塞策略；存储慢时只增加明确的 storage-drop 指标，不能阻塞实时投递。
2. **解除帧缓冲所有权耦合。** 为存储使用独立拷贝/缓冲池，或实现可靠的引用计数，使 SD 延迟不会耗尽采集和实时输出使用的共享池。
3. **改用 SDIO DMA/中断或分段状态机。** 至少避免在高优先级任务里同步等待完整块写入。
4. **修复启动恢复调度。** 全盘扫描应低优先级、分片执行并定期让出 CPU；CDC 控制和状态查询应在扫描期间可用，并报告 `RECOVERING` 与进度。
5. **减少不必要的全盘恢复。** 强化双 superblock 的提交顺序和掉电一致性；逻辑 clear 后保证空状态检查点与首数据块一致，避免下一次启动误入全盘扫描。
6. **修复 Release 构建。** 本次诊断发现 Release 固件可枚举 USB 但控制命令无响应，说明存在优化敏感问题；修好后再用 Release 数据评估最终吞吐。
7. 如果板级走线支持，评估 4-bit SDIO 和更高时钟。这属于吞吐优化，不能替代实时/存储解耦。

## 验收标准

- 连续采集至少 10 分钟，裸 CDC 帧到达不再周期性出现 100 ms 以上空洞。
- 正常 SD 写延迟和人为注入慢写时，`POOL_FAIL` 不持续增长；存储降级有独立且可解释的计数器。
- GUI 绘图保持连续，协议 CRC 与序列统计正常。
- SD 满环、逻辑清空后、重启恢复三种状态分别测试。
- 启动恢复期间 COM6 控制命令可响应，状态能显示恢复进度。

## 证据文件

- `raw-ab.json`：原始裸 CDC / UART 对照
- `raw-after-clear.json`：逻辑清空后的裸 CDC / UART 对照
- `gui.json`、`gui-baseline.json`、`gui-after-clear.json`：GUI 时序数据
- `sd-clear.json`：清空命令与状态快照
- `build/stutter-investigation/firmware/profile-debug.bin`：插桩计数器 SRAM 读回
- `build/stutter-investigation/firmware/original-flash.bin`：实验前完整 512 KiB Flash 备份

## 当前设备状态

实验结束时已把实验前的完整 512 KiB Flash 镜像写回并通过逐字节校验。板载 SD 的逻辑归档已按用户授权清空，之后测试又写入了少量新数据；逻辑清空无法恢复。设备当前正在固件的 SD 全盘恢复扫描中，COM6 已枚举，但扫描期间控制任务被高优先级存储任务饿死，因此 AT 命令暂时无响应。
