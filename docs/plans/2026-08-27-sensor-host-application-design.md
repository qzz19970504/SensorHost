# PyQt 传感器采集上位机设计

> 基于 SDF1 的 CDC 优先桌面上位机，提供无损采集、实时三轴振动绘图、JY61PL 3D 姿态和链路诊断。

**Module:** Sensor Acquisition / Desktop Host

**Status:** Approved Design

**Approved:** 2026-08-27

**Implementation:** Planned

## 1. Context

当前 STM32 已通过 USB CDC 输出版本化的 SDF1 二进制流。ESP32 固件尚未实现，因此上位机第一阶段只连接 CDC；后续 ESP32 上行只需实现新的 transport adapter，不改变协议、解码、录制和 UI。

视觉方向继承 `D:\Codes\STM32\stem-hub-host` 的深色工业仪表盘：深海军蓝背景、蓝灰卡片边界、青色主状态、紧凑等宽数据字体和克制的高亮。参考仓库只作为视觉输入，不在本功能中修改或复用其业务代码。

已批准的布局是“双焦点仪表盘”：左侧约三分之二显示 IIS3DWB 三轴振动时域图，右侧上方显示 JY61PL 3D 姿态，右侧下方显示欧拉角、加速度和温度，底部显示链路健康指标。

## 2. User Story

**As a** 固件与传感器开发者，

**I want** 在同一个 PyQt 应用中稳定接收、录制和观察 IIS3DWB 与 JY61PL 数据，

**So that** 可以判断传感器时序、数据质量和 MCU 传输状态，而不依赖临时测试脚本。

## 3. Goals and Non-goals

### Goals

- CDC 设备发现、连接、断开和受控重连。
- 复用固件 golden frames 的 SDF1 流式解析和兼容性测试。
- 原始数据完整录制与 UI 降采样显示解耦。
- IIS3DWB XYZ 实时时域图，X 轴为重建后的时间，Y 轴为 g。
- JY61PL 设备模型按 roll/pitch/yaw 旋转，并显示坐标轴和加速度向量。
- STATUS、CRC、sequence gap、drop、DMA/CDC 错误和栈余量诊断。
- CLI 控制 `status`、`acq start|stop` 和 watermark。
- 为未来 ESP32 上行保留 transport adapter。

### Non-goals

- 不从加速度积分绝对位置或绘制伪轨迹。
- 第一版不要求原始陀螺仪和磁力计，因为当前 JY61PL payload 不包含这些字段。
- 第一版不做频域分析、报警规则、云同步或复杂文件管理。
- 不在 GUI 线程读取串口、解析大帧、写盘或计算全量绘图数据。
- 不修改参考项目 `stem-hub-host`。

## 4. Technical Decision

### Selected

```text
PyQt6
  + pyserial
  + pyqtgraph
  + pyqtgraph.opengl
  + numpy
  + pytest / pytest-qt
```

串口采集运行在独立 `QThread` 中；协议解析和录制不依赖 UI。GUI 使用定时刷新从有界快照读取显示数据，不为每个传感器样本发送 Qt signal。

### Alternatives

| Option | Advantages | Costs | Decision |
|---|---|---|---|
| PyQt6 + pyqtgraph + pyqtgraph.opengl | 单一 Qt 事件循环、时域图成熟、依赖适中 | 3D 效果偏工程化 | Selected |
| PyQt6 + pyqtgraph + VisPy | 更强 GPU 3D 和大点云能力 | 依赖、上下文和测试复杂度更高 | Deferred |
| PyQt6 + QWebEngine + Three.js | 3D 表现丰富 | 进程和桥接更重，部署体积大 | Rejected for V1 |

## 5. Architecture

```text
PyQt presentation
  -> AcquisitionController
       -> Transport interface -> CdcSerialTransport
       -> Sdf1StreamParser
       -> FrameDecoder
       -> RealtimeSampleStore
       -> RawSessionRecorder

Presentation refresh timer
  -> RealtimeSampleStore.snapshot()
  -> VibrationView / OrientationView / DiagnosticsView
```

依赖方向始终从 presentation 指向应用逻辑，再指向 transport/storage 适配器。协议解析器是无 Qt 的纯 Python 模块，可直接用于测试、回放和未来 ESP32 transport。

### 5.1 Repository Layout

```text
host/
  README.md
  pyproject.toml
  src/sensor_host/
    app.py
    presentation/
      main_window.py
      vibration_view.py
      orientation_view.py
      diagnostics_view.py
      console_view.py
      theme.py
    acquisition/
      controller.py
      sample_store.py
      models.py
    protocol/
      sdf1.py
      decoders.py
      timestamps.py
    transport/
      base.py
      cdc_serial.py
    storage/
      recorder.py
      replay.py
      export_csv.py
  tests/
    unit/
    integration/
    visual/
```

`test/protocol.py` 中已经验证的算法在测试保护下提取到 `host/src/sensor_host/protocol/`；固件测试改为从新公共模块或兼容包装层导入，避免复制两份解析器后产生漂移。

## 6. Public Interfaces

### 6.1 Transport

```python
class Transport(Protocol):
    def discover(self) -> list[DeviceDescriptor]: ...
    def open(self, device_id: str) -> None: ...
    def close(self) -> None: ...
    def read(self, max_bytes: int, timeout_s: float) -> bytes: ...
    def write_control(self, command: bytes) -> None: ...
    def status(self) -> TransportStatus: ...
```

V1 只有 `CdcSerialTransport`。未来 ESP32 TCP/WebSocket adapter 仍返回相同原始 SDF1 字节，并复用其余模块。

### 6.2 Protocol Parser

```python
class Sdf1StreamParser:
    def feed(self, chunk: bytes) -> list[Sdf1Frame]: ...
    def metrics(self) -> ParserMetrics: ...
    def reset_session(self) -> None: ...
```

职责：magic 搜索、长度校验、CRC、未知版本安全跳过、sequence 回绕和缺口统计。解析器不换算传感器数值，不依赖 Qt。

### 6.3 Frame Decoders

```python
decode_iis3dwb(frame) -> IisBatch
decode_jy61pl(frame) -> Jy61Sample
decode_status(frame) -> FirmwareStatus
decode_cli_response(frame) -> str
```

IIS 解码器保留未知 FIFO tag，扩展 32 位传感器 timestamp 回绕，并用 MCU `timestamp_us` 锚定时间轴。JY 解码器只输出 acceleration、temperature、roll、pitch 和 yaw。

### 6.4 Acquisition Controller

```python
class AcquisitionController:
    def connect(self, device_id: str) -> None: ...
    def disconnect(self) -> None: ...
    def start_acquisition(self) -> None: ...
    def stop_acquisition(self) -> None: ...
    def set_watermark(self, words: int) -> None: ...
    def request_status(self) -> None: ...
    def start_recording(self, path: Path) -> None: ...
    def stop_recording(self) -> RecordingSummary: ...
```

控制命令串行排队并关联来源；连接状态机负责关闭、重连退避和会话统计重置。V1 UI 不显示 UART transport 切换控件，避免在 CDC-only 阶段误切到未连接链路；CLI 控制台仍可用于显式调试。

### 6.5 Realtime Store

```python
class RealtimeSampleStore:
    def append_iis(self, batch: IisBatch) -> None: ...
    def update_jy(self, sample: Jy61Sample) -> None: ...
    def update_status(self, status: FirmwareStatus) -> None: ...
    def snapshot(self, window_s: float, max_points: int) -> UiSnapshot: ...
```

store 保存有界时间窗和最新状态。`snapshot()` 返回不可变或复制后的数组，执行 min/max envelope 或等价降采样；GUI 不直接持有采集线程的可变容器。

### 6.6 Storage

原始录制文件是连续 SDF1 帧，建议扩展名 `.sdf1`；旁边写同名 `.json` 会话元数据，包括应用版本、协议版本、设备、开始时间、结束时间、计数器和用户配置。CSV 是离线导出结果，不作为实时权威记录。

## 7. User Interface

### 7.1 Global Header

- Tabs: `LIVE MONITOR`、`DIAGNOSTICS`、`CONSOLE`。
- CDC 设备选择、连接状态、断开、录制和深浅色切换。
- 断开时禁用采集控制，但允许刷新设备列表和打开回放。

### 7.2 Live Monitor

- 工具栏：IIS3DWB 标识、26.667 kHz、显示窗 1/5/10/30 s、watermark 128/256/511、暂停显示、录制。
- 左侧振动图：X 红、Y 绿、Z 蓝，通道显隐、自动 Y 轴、时间轴和单位。
- 右上姿态：简单设备模型、XYZ 世界轴、加速度向量；roll/pitch/yaw 更新模型旋转。
- 右下指标：欧拉角、JY 加速度 XYZ、合加速度和温度。
- 底部状态：samples/s、CRC、sequence gap、source/transport drop、CDC busy、uptime 和录制状态。

“暂停”只暂停显示快照，不暂停采集或原始录制；采集启停必须使用明确的 `acq start|stop`。

### 7.3 Diagnostics

- 完整 STATUS 字段和任务栈 high-water。
- parser、连接和 recorder 指标。
- 最近错误的时间、来源和可操作说明。
- 指标可复制，但不在高频路径逐帧追加文本。

### 7.4 Console

- 发送一行 ASCII CLI，自动添加 CRLF。
- 分离发送、CLI_RESPONSE 和本地日志样式。
- 限制历史行数，禁止二进制 SDF1 直接渲染为文本。

## 8. 3D Orientation Semantics

姿态视图表示设备相对世界坐标系的方向，不表示绝对位置。

- 输入：JY61PL roll、pitch、yaw。
- 模型：带方向标记的矩形传感器板，避免视觉上无法判断 180° 翻转。
- 辅助：固定世界 XYZ 轴、设备局部轴和当前加速度向量。
- 无新 JY 数据时保持最后姿态并显示 stale 时长；超过阈值降低颜色强调。
- 不绘制位移轨迹，不把加速度二次积分结果展示为位置。

## 9. Concurrency and Performance

- 串口 worker 使用阻塞 read 或事件驱动 read，禁止 GUI 线程轮询串口。
- 采集热路径按 chunk 通知，不为约 26.7 kHz 的每个样本发 signal。
- UI 刷新目标 30 Hz；3D 可按 JY 输出率刷新，不插值伪造数据。
- 每通道单次绘制默认不超过 5,000 点；显示降采样不能改变原始录制。
- 录制写入使用有界队列和批量写；磁盘持续落后时显式报错并停止录制，不能反压串口至无界内存增长。
- CDC 路径至少承受当前流量 2 倍的软件回放压力，持续运行内存不随时间增长。

## 10. Error Handling

- 串口拔出：结束本次连接会话、关闭句柄、保留已完成录制并指数退避重连。
- CRC/长度错误：解析器重同步，UI 增加指标，不弹出逐帧对话框。
- sequence gap：标记录制索引和状态，不停止后续有效数据。
- 写盘失败：停止录制并显示明确路径和错误；采集与实时显示继续。
- OpenGL 不可用：姿态页降级为欧拉角仪表和 2D 坐标示意，其余功能可用。
- 固件未知版本：保存原始帧并提示不兼容，不误用 V1 decoder。

## 11. Testing

### Unit

- SDF1 任意分片、拼接、垃圾、CRC、长度、未知类型和 sequence 回绕。
- IIS tag、timestamp 回绕和 JY 固定点换算。
- ring window、降采样和状态 stale 逻辑。
- 录制文件和元数据原子结束行为。

### Integration

- 使用 `test/golden/stream_v1_frames.bin` 驱动完整 parser/decoder。
- fake transport 以突发、慢速、断开和损坏数据驱动 controller。
- CDC 实板执行 connect、status、stop/start、watermark 和持续录制。

### UI and Visual

- pytest-qt 验证连接、禁用、暂停、录制和错误状态。
- 固定字体和窗口尺寸生成关键页面截图基线。
- 3D 不以像素级完全一致为硬门禁，但验证姿态矩阵、stale 和降级状态。

## 12. Acceptance Criteria

- [ ] Windows 上可发现并连接 STM32 CDC。
- [ ] 连续 SDF1 数据无 UI 卡顿，解析指标与参考 Python 实现一致。
- [ ] XYZ 振动曲线使用重建时间，单位和颜色清晰。
- [ ] 3D 模型按 roll/pitch/yaw 转动，并显示加速度向量和 stale 状态。
- [ ] UI 不声称显示绝对位置或完整原始九轴数据。
- [ ] `status`、`acq start|stop` 和 watermark 控制可用。
- [ ] 原始 `.sdf1` 录制可回放，CRC/sequence 指标可复现。
- [ ] 串口断开、CRC 错误和写盘错误不会导致无界内存增长或进程崩溃。
- [ ] 无 OpenGL 时除 3D 外的采集、录制和诊断仍可使用。
- [ ] CDC 实板持续测试通过后才把当前 CDC 上位机阶段标为完成。

## 13. Open Questions

- **Resolved:** V1 使用 PyQt6、pyqtgraph 和 pyqtgraph.opengl。
- **Resolved:** 默认页面为双焦点仪表盘。
- **Resolved:** 姿态显示方向和加速度向量，不计算绝对位置。
- **Resolved:** 当前测试只走 CDC；ESP32 transport 后续增加。
- **Resolved:** 上位机放入当前仓库独立 `host/` 子项目，参考仓库不修改。
- **Open:** 第一版是否同时实现离线 CSV 导出；原始 SDF1 录制和回放不受此项影响。

## 14. Related Documents

- [SDF1 V1 通讯协议](../PROTOCOL.md)
- [ESP32 通讯网关交接需求](../ESP32_GATEWAY_REQUIREMENTS.md)
- [后续实现路线图](../ROADMAP.md)

## 15. Revision History

| Date | Author | Change |
|---|---|---|
| 2026-08-27 | Codex | 记录已批准的功能、PyQt 技术方案和双焦点 UI 设计 |
