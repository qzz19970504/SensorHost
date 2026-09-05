# STM32 Sensor Host

PyQt6 desktop host for SDF1 acquisition over STM32 USB CDC or up to 16
ESP32 UART-to-TCP gateways.

## Five-minute quick start

在仓库根目录执行。以下命令使用 Codex 工作区缓存中的 Python，不依赖系统 Python：

```powershell
$CodexPython = 'C:\Users\44575\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $CodexPython -m venv .\host\.venv
```

预期：生成 `host/.venv/`，命令正常退出且不修改固件构建环境。

```powershell
& .\host\.venv\Scripts\python.exe -m pip install -e '.\host[dev]'
```

预期：安装 `stm32-sensor-host`、PyQt6、pyqtgraph、pyserial、NumPy 和测试依赖。若默认源访问慢，可追加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`。

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& .\host\.venv\Scripts\python.exe -m pytest .\host\tests .\test\test_protocol.py -q
Remove-Item Env:QT_QPA_PLATFORM
```

预期：全部测试通过；测试覆盖 SDF1、采集控制、有界缓存、原始录制/回放、Qt 线程退出和关键界面行为。

```powershell
& .\host\.venv\Scripts\stm32-sensor-host.exe
```

预期：出现深色 `STM32 SENSOR DESKTOP` 窗口。CDC 模式选择 STM32 对应的
COM 口后点 `CONNECT`；Wi-Fi 模式选择手机热点网卡后点 `START LISTENER`。
程序不会自动打开第一个串口，也不会自动执行 START、STOP 或切换实时目标。

## What this does and does not do

当前版本通过 STM32 USB CDC 或 ESP32 透明 TCP 透传接收同一套 SDF1，显示
IIS3DWB 三轴振动时域数据、JY61PL 姿态/加速度/温度、完整固件状态和解析健康
指标。Wi-Fi 现场模式由 PC 监听 TCP，可同时管理 16 个一对一 ESP32/STM32
节点；每个节点拥有独立解析器、命令队列、图表、诊断和录制文件。

姿态动画表示设备方向，不表示绝对位置。当前 JY61PL payload 也不包含原始陀螺仪和磁力计通道，因此界面不声称显示完整原始九轴数据。V1 不包含通用文件管理器、频谱、报警、云同步或 CSV 导出；CSV 在出现明确分析需求后再做离线导出。

## Prerequisites

- Windows 10/11。
- STM32 已烧录本仓库固件并能枚举 USB CDC 虚拟串口。
- Wi-Fi 模式下，PC 和 ESP32 必须连接同一个手机热点；热点必须允许客户端间
  通信，Windows 防火墙必须允许上位机 TCP 入站。
- ESP32 中预设的 PC IPv4 与 TCP 端口必须和上位机选择的热点网卡一致。
- 缓存 Python 3.11+，或兼容的系统 Python。
- 若需要 3D 姿态，显卡驱动和 Qt OpenGL 必须可用；否则自动使用 2D 降级视图。

CDC 适配器构造时使用 `115200` 作为串口 API 的占位值；USB CDC 的实际线速不由该波特率选择决定。

## Packaged Windows build

在仓库根目录运行以下命令可生成经过源码测试和启动自检的单文件 Windows x64 EXE：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\package_host.ps1
```

产物写入 `dist/host/STM32SensorHost-<version>-win64.exe`，同目录 JSON 保存文件大小和 SHA-256。Python 选择顺序、隔离 venv、依赖升级、校验方式和常见问题见 [`docs/HOST_BUILD_ENVIRONMENT.md`](../docs/HOST_BUILD_ENVIRONMENT.md)。

## Setup

可编辑安装便于开发时直接加载 `host/src/` 的修改：

```powershell
& .\host\.venv\Scripts\python.exe -m pip install -e '.\host[dev]'
```

运行源码编译检查：

```powershell
& .\host\.venv\Scripts\python.exe -m compileall -q .\host\src .\host\tools
```

## Usage

1. 调试时选择 `CDC`、刷新 COM 口并点 `CONNECT`；现场使用时选择 `WI-FI`。
2. Wi-Fi 模式选择手机热点网卡，确认其 IPv4 等于所有 ESP 固件预设的服务器
   地址，设置 TCP/UDP 端口后点 `START LISTENER`。默认端口为 TCP 54321、UDP
   12345；上位机会广播 `TCPCONNECT`，也可填写 ESP IPv4 进行单播唤醒。
3. 从左侧 `DEVICES` 选择节点；列表显示别名、UUID、对端 IP、连接、录制和告警状态。
4. `LIVE MONITOR` 查看当前节点的三轴波形、姿态和健康栏。
5. `PAUSE` 只冻结当前显示；采集和全部原始录制继续。
6. `DIAGNOSTICS` 查看当前节点的 parser、host、二进制 STATUS 及
   `+STATE/+SD/+LIVE/+DIAG/+EXPORT` 结构化状态。
7. `CONSOLE` 命令只发送给当前选中节点。程序连接后只自动查询 UUID、STATE 和
   LIVESTREAM，不自动执行任何写命令。
8. 结束前点 `DISCONNECT`；Wi-Fi 监听和全部节点会话会一起安全停止。

## Recording and replay

点 `RECORD` 后，每个已识别的在线节点分别写入；录制期间新接入节点也会加入：

```text
host/recordings/<batch-UTC>/<alias>-<uuid8>/segment-001.sdf1
host/recordings/<batch-UTC>/<alias>-<uuid8>/segment-001.json
```

断线重连会创建下一个 segment，不把断线前后伪装成连续数据。带
`ARCHIVE_EXPORT` 标志的历史帧不进入实时图，而是保存到 `host/exports/` 下的
独立文件。显示降采样不会改变已保存帧；写盘队列有容量上限。

当前回放能力作为无 Qt 的 Python 接口和自动化测试提供，尚未做成文件浏览页面。验证录制/回放路径：

```powershell
& .\host\.venv\Scripts\python.exe -m pytest .\host\tests\test_recorder_replay.py .\host\tests\test_replay_performance.py -q
```

## Project structure

```text
host/
  pyproject.toml                   Python 包、依赖和命令入口
  src/sensor_host/
    app.py                         PyQt composition root
    acquisition/                   Qt-free controller and bounded sample store
    presentation/                  multi-node connection, live, diagnostics and console views
    protocol/                      authoritative SDF1 and control-state parsers
    storage/                       bounded raw recorder and replay helpers
    transport/                     CDC, accepted TCP and UDP wake adapters
  tests/                           unit, integration, Qt and visual baselines
  tools/capture_visual_baseline.py deterministic screenshot generator
```

固件旧测试通过 `test/protocol.py` 兼容导入同一权威解析器，避免两份协议实现漂移。

## Configuration

- 显示窗口：1、5、10 或 30 秒，默认 10 秒。
- UI 快照上限：每次最多 5,000 个保峰值点。
- UI 刷新：约 30 Hz。
- IIS3DWB watermark：128、256 或 511 words，默认 511。
- 姿态 stale 阈值：0.5 秒。
- CDC 读取超时：50 ms，用于保证断开时线程能及时退出。

watermark 越小，中断/批次频率越高、单批延迟通常越低；watermark 越大，CPU/DMA 调度次数较少但单批延迟更高。

## UART/CDC 与 SD 实机验收

生产双路验收先列出串口，再同时采集 UART2 与 STM32 CDC。工具只通过 CDC
发送控制命令，不发送 ACK；每种模式输出 JSON 与两份原始 `.sdf1`：

```powershell
python .\host\tools\dual_output_acceptance.py --list-ports
python .\host\tools\dual_output_acceptance.py --cdc-port COM5 --uart-port COM8 --uart-baud 115200 --duration 30 --output .\host\tests\golden\hardware\dual-output.json
```

```powershell
$Python = 'C:\Users\44575\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $Python .\host\tools\realtime_archive_acceptance.py --list-ports
& $Python .\host\tools\realtime_archive_acceptance.py --mode preflight --cdc-port COM6 --uart-port COM12 --uart-baud 115200 --output .\build\hw-preflight.json
& $Python .\host\tools\realtime_archive_acceptance.py --mode live --cdc-port COM6 --uart-port COM12 --uart-baud 115200 --duration 30 --output .\build\hw-live.json
& $Python .\host\tools\realtime_archive_acceptance.py --mode overwrite --cdc-port COM6 --uart-port COM12 --uart-baud 115200 --duration 1800 --output .\build\hw-overwrite.json
& $Python .\host\tools\realtime_archive_acceptance.py --mode export-uart --cdc-port COM6 --uart-port COM12 --uart-baud 115200 --duration 30 --output .\build\hw-export-uart.json
& $Python .\host\tools\realtime_archive_acceptance.py --mode export-cdc --cdc-port COM6 --uart-port COM12 --uart-baud 115200 --duration 30 --output .\build\hw-export-cdc.json
& $Python .\host\tools\realtime_archive_acceptance.py --mode interrupt-export --cdc-port COM6 --uart-port COM12 --uart-baud 115200 --duration 30 --output .\build\hw-interrupt-export.json
```

工具为 UART 和 CDC 建立独立 reader/parser，实时写出 `.uart.sdf1`、`.cdc.sdf1`，STOP 等到固件返回 OK/IDLE 及在途发送稳定后才进入下一步。覆盖模式只保留计数器，不把整个 CDC 流存入内存。导出模型要求 UUID、SDF v2 头、CRC、长度、payload、IIS/JY 类型、ARCHIVE_EXPORT 标志和 `(UUID, sequence)` 去重后无缺帧；UART/CDC 目标口不得出现交叉历史帧。中断导出允许同一 chunk 重复，但不允许缺帧。

合并前的最终门禁不是“窗口能打开”，而是 CDC 端到端持续验证。连接硬件后应完成：

- 发现正确 STM32 CDC COM 口并连接/断开。
- `status`、`acq stop/start` 和三档 watermark 有响应。
- XYZ 曲线持续更新，GUI 操作不冻结。
- JY 有帧时姿态更新；无帧时显示 waiting/stale。
- 原始录制结束后可完整回放。
- CRC、sequence gap、source drop、transport drop、FIFO overrun 增量均为 0。

自动化验收工具与五分钟 CDC smoke 将在本阶段最后一步运行。硬件通过前，UART/ESP32 不计入当前上位机门禁。

## Troubleshooting

- 找不到 COM 口：确认 Windows 设备管理器中的 STM32 Virtual COM Port，重新插拔 Type-C 后点 `REFRESH`。
- ESP 不连接：确认 PC/ESP 在同一手机热点、PC IPv4 与 ESP 预设地址完全一致、
  TCP/UDP 端口一致；关闭热点“客户端隔离”，并允许 Windows 防火墙 TCP 入站。
- UDP 广播无效：从手机热点的已连接设备页面取得 ESP IPv4，填入可选单播目标。
- 误选 CH340：PA2/PA3 上的 CH340 是 UART2 调试链路，不是当前 GUI 的 STM32 CDC 数据口。
- 有连接但无曲线：在 `CONSOLE` 发送 `status`，确认 `acquisition_state`、IIS 接线和固件错误计数。
- 姿态显示 `WAITING`：JY61PL 可以缺席而不影响 IIS/CDC 完整性；检查 USART1 接线和模块输出。
- 姿态显示 `2D FALLBACK`：Qt OpenGL 不可用；数值、采集、录制和诊断仍然有效。
- 文本显示方框：入口会显式加载 Segoe UI/Consolas；确认 `C:\Windows\Fonts` 中字体存在。
- 退出延迟：串口 read 最迟约 50 ms 返回；若超过三秒，控制台会报告线程未停止而不会强制终止。

## Contributing

功能或缺陷修改遵循测试先行。提交前至少执行：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& .\host\.venv\Scripts\python.exe -m pytest .\host\tests .\test\test_protocol.py -q
& .\host\.venv\Scripts\python.exe -m compileall -q .\host\src .\host\tools
git diff --check
```

协议变更还必须同步更新 `docs/PROTOCOL.md`、golden frames、固件 C 测试和 Python 测试。
