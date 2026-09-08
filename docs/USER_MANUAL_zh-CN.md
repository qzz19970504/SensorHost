# SensorHost 上位机操作手册

本文适用于 `D:\Codes\SensorHost` 上位机和 STM32F407 传感器固件，重点说明
USB CDC（虚拟串口）连接、实时采集、记录、诊断和历史数据导出。

## 1. 使用前准备

### 1.1 硬件

- STM32F407 采集板已正常上电并运行目标固件。
- USB 数据线连接板卡的 USB Device 接口与电脑。
- Windows 设备管理器的“端口（COM 和 LPT）”中应出现
  `USB 串行设备 (COMx)`。

本次实机中 CDC 为 COM6，硬件 ID 是：

```text
USB\VID_0483&PID_5740\2089329D3147
```

`VID_0483&PID_5740` 可用于辨认 STM32 CDC。COM 号可能在换 USB 插口、换电脑
或重新安装设备后变化，因此不要永久假定所有电脑都是 COM6。当前电脑另有
COM12（FTDI USB Serial Port），它不是本次 STM32 CDC 口。

### 1.2 软件

从源码运行需要 Python 3.11 或更高版本。首次安装：

```powershell
Set-Location D:\Codes\SensorHost
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e '.[dev]'
```

启动上位机：

```powershell
Set-Location D:\Codes\SensorHost
& .\.venv\Scripts\stm32-sensor-host.exe
```

如果使用已经打包的单文件程序，直接运行发布目录中的
`STM32SensorHost.exe`，不需要单独安装 Python。

## 2. 界面控件

顶部连接区：

- `CDC / WI-FI`：选择物理数据通路。
- 设备下拉框：CDC 模式下选择 COM 口。
- `REFRESH`：重新扫描串口和网络接口。
- `CONNECT`：打开选中的 CDC 口；该动作只连接并查询设备，不会自动 START、
  STOP 或切换实时输出目标。
- `CONNECT` / `DISCONNECT`：同一个按钮随连接状态切换；Wi-Fi 模式下负责启动或关闭监听及其连接。断开不会自动修改固件的实时目标。
- TCP 连接连续 20 秒未收到任何字节时会自动关闭并释放名额；程序每 5 秒查询一次状态，正常回复的空闲设备不会被清理。
- 错误横幅：连接/命令/写盘等错误会在工具栏下方以非模态横幅显示（任意页面
  可见），可点击 `CLEAR` 关闭；原始错误同时保留在 CONSOLE。

采集工具栏：

- `WINDOW`：图表显示时间窗；不限制文件记录时长。
- `FIFO WM`：设置 IIS3DWB FIFO watermark，可选 128、256、511。
- `LIVE TARGET`：选择固件实时数据唯一输出目标，`UART` 或 `CDC`。
- `START`：发送 `AT+START`，启动采集。
- `STOP`：发送 `AT+STOP`，停止采集并等待 SD 和实时链路完成收尾。
- `PAUSE`：只暂停界面刷新，不停止固件采集，也不停止记录。暂停时振动卡显示
  `DISPLAY PAUSED` 徽标、姿态区显示 `DISPLAY PAUSED`，提醒当前数值为冻结值。
- `RECORD`：开始或停止上位机原始 SDF1 文件记录。按钮文字显示当前实际正在
  记录的会话数（如 `● RECORD · 2`）；写盘失败会在错误横幅与 Console 提示。
- `CLEAR`（振动卡）：清空当前节点的曲线历史，暂停时也可使用；后续采样继续显示，不影响其他节点或录制文件。
- `RESET VIEW`（振动卡）：手动缩放/平移后恢复跟随最新采样时间窗。
- `RESET LAYOUT`（顶部）：恢复默认分隔器比例与窗口尺寸。

节点侧栏（所有页面左侧）：

- `DEVICES` 列表显示各节点别名、UUID 后 8 位、对端地址与状态；离线/重连节点
  仅供查看，不能被选为命令目标，命令只会发往当前高亮的在线节点（`TARGET`
  行常显当前目标别名与 UUID）。
- 别名输入框中未保存的草稿在列表刷新时不会丢失；`SAVE ALIAS` 仅在别名为
  1..64 字符且存在选中节点时可用。

页面：

- `LIVE MONITOR`：IIS3DWB 三轴振动和 JY61PL 姿态数据显示；姿态区状态为
  `WAITING`/`LIVE`/`STALE`/`DISPLAY PAUSED`/`OFFLINE`。
- `DIAGNOSTICS`：解析器、固件、链路和存储计数器；长错误自动换行且可用鼠标
  选中复制；尚未收到固件状态的计数显示 `—` 而非 0。
- `CONSOLE`：查看固件回复或发送高级 AT 命令。每条记录带接收时间戳；提供
  搜索框、`FOLLOW`（关闭后阅读历史不自动滚底）、`ALL NODES`（显示非所选节点
  回复并标注来源）、`CLEAR DISPLAY`（仅清显示）与可折叠的 `EXPORT HELP` 指引。

## 3. COM6 冷启动采集步骤

固件冷启动默认为 `IDLE` 且 `LIVESTREAM=UART`。因此仅点击 CONNECT 后没有
曲线是正常现象，必须显式选择 CDC 并启动采集。

1. 板卡上电并连接 USB。
2. 启动 SensorHost，顶部选择 `CDC`。
3. 点击 `REFRESH`，选择 `COM6 — USB 串行设备`。若 COM 号变化，按
   `VID_0483&PID_5740` 确认实际端口。
4. 点击 `CONNECT`，连接状态应变为 `CONNECTED`，左侧节点列表出现当前设备。
5. 确认左侧节点已选中。
6. 在 `LIVE TARGET` 中选择 `CDC`。Console 应显示固件返回 `OK`，后续状态中
   应看到 `+LIVESTREAM:CDC` 或 `+LIVE:TARGET=CDC`。
7. 点击 `START`。Console 应显示 `OK`，随后 LIVE MONITOR 开始刷新，
   `SAMPLES/S` 和接收帧计数开始增加。

CDC 是 USB 传输，界面底层使用的 115200 只是 Windows 串口 API 的占位设置，
不会限制 USB CDC 的实际吞吐率。

## 4. 从正在运行的 UART 切换到 CDC

固件只允许在 IDLE 状态切换实时目标。如果设备已处于 ACQUIRE 且当前目标为
UART，直接选择 CDC 会收到 `ERROR:STATE`。正确顺序如下：

1. 点击 `STOP`。
2. 在 Console 中等待 `OK`，并确认 DIAGNOSTICS/Console 显示状态为 `IDLE`。
3. 将 `LIVE TARGET` 选择为 `CDC`，等待 `OK`。
4. 点击 `START`，等待 `OK`。
5. 确认 LIVE MONITOR 有实时数据，CRC ERR 和 LINK ERR 没有增加。

切回 UART 使用同样顺序：STOP → 等待 IDLE/OK → 选择 UART → START。

## 5. 实时监看与健康判断

正常 CDC 会话应满足：

- `SAMPLES/S` 为非零并持续更新。
- IIS3DWB 曲线持续滚动；JY61PL 更新频率较低，短时间只出现少量姿态帧属于正常。
- `CRC ERR` 不增加。
- `SOURCE DROP`、`TRANSPORT DROP`、`LINK ERR` 在稳定链路下不增加。
- CDC 目标正常负载下 `LIVE DROP` 应保持 0。

`PAUSE` 只冻结显示。需要真正停止板端采集时必须点击 `STOP`。

尚未收到固件状态或控制状态时，`SOURCE DROP`、`TRANSPORT DROP`、`LINK ERR`、
`LIVE DROP` 等显示 `—`（未知）而不是 0；收到状态后才显示实际计数。断开连接后
姿态区显示 `OFFLINE`，不会把最后一次的姿态当作实时值。

## 6. 数据记录

1. 先连接设备并确认节点 UUID 已显示。
2. 点击 `RECORD` 开始记录；按钮保持选中状态。
3. 正常监看或切换显示时间窗不会影响原始记录。
4. 再次点击 `RECORD` 停止并完成文件写入。
5. 退出程序前建议先停止 RECORD，再 STOP，最后 DISCONNECT。

Windows 默认数据目录：

```text
%LOCALAPPDATA%\SensorHost\
  recordings\<批次>\<别名>-<uuid8>\segment-001.sdf1
  recordings\<批次>\<别名>-<uuid8>\segment-001.json
  exports\<批次>\<别名>-<uuid8>\export-001.sdf1
```

要改用其他目录，在启动程序前设置绝对路径：

```powershell
$env:SENSOR_HOST_DATA_DIR='D:\SensorData'
& .\.venv\Scripts\stm32-sensor-host.exe
```

已有记录不会自动搬迁。

## 7. SD 历史数据导出

历史导出与实时 RECORD 不同：RECORD 保存连接后收到的实时帧；EXPORT 从板卡
SD 中读取历史 SDF1 数据。

1. 点击 `STOP` 并等待固件进入 IDLE。
2. 确认左侧选中了目标节点，且节点 UUID 已获取。
3. 打开 `CONSOLE`。
4. CDC 导出输入 `AT+EXPORT=CDC` 并发送。
5. 等待 `EXPORT_BEGIN`，完成时会收到
   `EXPORT_END:CHUNKS=<n>,FRAMES=<n>`；空存档返回 `EXPORT_EMPTY`。
6. 导出文件保存在默认数据目录的 `exports` 下。

导出期间不要 START 或拔线。连接中断会把本次导出标记为中止；重新导出允许
最多重复一个 SD chunk，上位机按协议保存接收到的完整帧。

## 8. 安全停止和退出

建议按以下顺序结束：

1. 如果 RECORD 正在运行，再点一次 `RECORD` 完成文件写入。
2. 点击 `STOP`，等待 Console 返回 `OK`。
3. 如果后续要由 ESP32/UART 接收实时数据，在 IDLE 下把 `LIVE TARGET` 改回
   `UART`；需要继续运行时再点击 `START`。
4. 点击 `DISCONNECT`。
5. 关闭 SensorHost。

仅关闭串口不会替代 STOP。固件会保持它自己的采集状态和实时目标。

## 9. 常见问题排查

### 找不到 COM6

- 点击 `REFRESH`。
- 在设备管理器确认 USB 串行设备是否存在。
- 检查硬件 ID 是否包含 `VID_0483&PID_5740`。
- 更换支持数据传输的 USB 线或 USB 插口。
- COM 号可能已变为 COM5、COM7 等，应选择硬件 ID 匹配的端口。

### 提示端口无法打开或 Access denied

COM 口已被另一个进程独占。关闭串口助手、旧的 SensorHost 实例或其他正在占用
该端口的软件，再点击 REFRESH 和 CONNECT。

### 显示 CONNECTED，但曲线没有数据

依次检查：

1. 左侧是否选中了当前节点。
2. Console 中 `AT+STATE?` 是否返回 `+STATE:IDLE`；若是，点击 START。
3. `LIVE TARGET` 是否为 CDC；若为 UART，先 STOP/等待 IDLE，再选择 CDC。
4. Console 是否出现 `ERROR:STATE`、`ERROR:BUSY` 或其他错误。
5. `DIAGNOSTICS` 中字节数和帧数是否增加。

### 选择 CDC 后出现 ERROR:STATE

设备正在采集且目标不同。点击 STOP，等待 OK/IDLE，再选择 CDC，最后 START。

### 选择 CDC 后出现 ERROR:BUSY

设备虽已进入 IDLE，但上一帧可能仍在完成发送。稍等片刻后重新选择 CDC；不要
连续快速点击 START/STOP/目标选择。

### 有字节但没有有效帧，或 CRC ERR 增加

- 确认选择的是 STM32 CDC，而不是 COM12 FTDI 或其他串口。
- 关闭所有同时读取该端口的软件。
- 断开并重新连接 USB 后重试。
- 在 Console 执行 `AT+STATE?`，记录回复以及 DIAGNOSTICS 的 CRC、丢弃和链路
  错误计数，供进一步定位。

### JY61PL 看起来更新很慢

IIS3DWB 是高频振动传感器，JY61PL 帧率远低于 IIS3DWB。只要姿态值间歇更新且
没有协议错误，通常不是 CDC 故障。

## 10. 本次 CDC 故障的判定依据

本次对 COM6 的实机短测结果：

- 控制查询收到 2 个合法 SDF1 响应帧，CRC 错误 0。
- 显式选择 CDC 并 START 后，3 秒收到 421,356 字节、121 个 IIS3DWB 帧和
  1 个 JY61PL 帧，CRC 错误及解析丢弃均为 0。
- STOP 成功，并恢复到 UART/IDLE。

因此固件封包、USB CDC 发送、Windows CDC 驱动、上位机串口读取及 SDF1 解析
均已走通。原问题是上位机 GUI 没有暴露切换目标和 START/STOP 操作入口；现已
通过采集工具栏提供这些显式控制。
