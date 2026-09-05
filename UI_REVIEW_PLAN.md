# UI/UX 审查与修改计划

## 0. 文档元信息

- 审查日期：2026-09-05；角色：UI/UX 审查负责人。
- 项目：`D:/Codes/SensorHost`；分支 `main`；提交 `398128e8a0da21939635aa03b256623282aad5e9`。开始审查时工作区干净。
- 目标：不改变设备及数据语义，给 Qoder 提供可独立验收的整改阶段。本轮仅新增本计划，未修改产品代码。
- 技术栈：【已确认】Python/PyQt6 Widgets，pyqtgraph 曲线，PyOpenGL 优先、QPainter 回退的姿态显示，QSettings，PyInstaller 单文件打包。声明版本见 `pyproject.toml`；本机 `.venv` 实测 Python 3.12.14、PyQt/Qt 6.11.0、pyqtgraph 0.14.0、NumPy 2.5.2。
- 审查方式：完整阅读 `src/sensor_host/presentation/` 全部 12 个 Python 文件及 `app.py`；检查 UI 数据、状态、线程、保存调用链；读取 UI 测试、视觉基线、截图工具、构建配置、操作手册及相关设计规范；运行源代码测试和离屏渲染。没有连接串口、启动实际网络监听、发送设备命令或执行硬件验收工具。
- 文件定位约定：下文 `P/` = `src/sensor_host/presentation/`，`A/` = `src/sensor_host/acquisition/`，`S/` = `src/sensor_host/storage/`，均相对于上述项目根目录；符号是主要定位，行号不作为执行依据。
- 扫描结果：【已确认】无项目自有 `.ui` 设计器、QSS/CSS 文件、QRC、SVG、ICO 或字体文件；样式由 `P/theme.py` 返回，资源为绘制几何、Unicode 文本、系统字体和测试 PNG。依赖库内部菜单、Qt 默认资源不属于自有 UI 源代码。未把 `.venv/build/dist` 的依赖副本当作独立页面。
- 本轮证据：`build/ui-review/current-live.png`；`build/ui-review/{CDC,WI-FI}-{1080,1440}-{0,1,2}-scale{1,1.25,1.5,2}.png`；`probe-1.25.json`、`probe-1.5.json`、`probe-2.json`；临时复现脚本 `audit_probe.py`、`target_probe.py`。这些在忽略的 build 目录，可能被打包清理；关键结论已写入本文，交接时应将需要的图片复制到阶段证据目录。
- 【已确认】源测试 `172 passed in 27.96s`；`python -m sensor_host.app --smoke-test` 退出 0；`compileall -q src tools` 退出 0。未重新构建 EXE，不能据此声称发布包通过。

## 1. 执行摘要

现有 UI 已具备三页导航、公共颜色和间距、可拖动分隔器、后台采集、限点快照、有限日志、姿态回退和基础测试，适合局部演进。主要不足是设备状态与展示状态衔接不完整、小窗口布局退化，以及测试偏向单控件结构而缺少真实组合状态。无需更换 UI 框架。

最影响体验的五项：

1. **UI-01/P0：列表高亮与实际命令目标可能不一致。** 选择离线节点后，控制器仍可能保留上一个在线目标，存在向非预期设备发送 START/STOP/参数命令的风险。
2. **UI-02/P1：监听成功等同于节点已连接。** 无节点时也启用采集、参数和录制操作。
3. **UI-03、UI-04/P1：冻结或断开后的数据仍像实时值。** 暂停提示未接线，断开仍保留姿态 LIVE，诊断可能跨节点残留。
4. **UI-05、UI-06/P1：录制和命令缺少可靠的结果反馈。** 按钮选中不等于文件写入成功，核心错误只在另一个 Tab 中。
5. **UI-07、UI-08/P1：最小窗口及高缩放空间不足。** 已复现 Wi-Fi 表单挤压；1080×700 的逻辑最小尺寸无法放进 1080p 的 200% 工作区。

问题计数（按唯一 ID，不重复计专项）：**P0 1 项，P1 8 项，P2 13 项，P3 2 项，共 24 项**。证据为代码事实、离屏复现或明确标注的推测；性能、真实 Windows DPI 和硬件时序尚未验收。

建议 6 个阶段（0–5）：先建立基线并封堵目标错位；再做基础样式；再处理状态、布局；然后曲线和日志；随后 DPI/可访问性；最后做必要的技术债收敛和发布回归。任何阶段不得以“界面更顺”为由自动 STOP、START、切换输出目标、重试设备命令或改变记录策略。

## 2. 事实、推测与限制

### 2.1 已确认

| 证据 | 结果与意义 |
|---|---|
| 全量 presentation 源码及 `app.py` | 只有 LIVE MONITOR、DIAGNOSTICS、CONSOLE 三个主 Tab；Wi-Fi 参数和节点列表是常驻侧区；没有历史回放页、设置窗口或自有模态弹窗 |
| `NodeSidebar._emit_selected_node` + 离屏信号探针 | 选 B 在线，再选 A 离线：高亮文本 A/OFFLINE，而最后发出的目标信号仍是 b；控制器的命令路由依据独立的 selected_node_id |
| `MainWindow.set_wifi_server_state(True, ...)` | 无节点时 START、RECORD 均 enabled；Console SEND 在断开状态也 enabled |
| `pause_button.click()` + app 接线 | PAUSE checked，但 VibrationView 暂停徽标 hidden；真正暂停由 AppController 控制快照发布 |
| 注入姿态后 `set_connected(False)` | ROLL 仍为 +12.40，Orientation 状态仍为 LIVE；这是视图方法复现，不是实际硬件掉线记录 |
| `NodeSidebar.set_nodes` 重复调用 | 编辑未保存别名后刷新同一列表，输入变回 A；完整重建列表触发 selection 事件 |
| 1080×700 Wi-Fi 离屏截图 | 标签与输入框挤压，说明文本被裁切；QSpinBox 比相邻输入矮；裸 QComboBox 无绘制箭头 |
| 旧 PNG 与本轮 PNG 对比 | 旧基线无侧栏、无 START/STOP/LIVE TARGET，不能代表当前主界面 |
| 数据与日志实现 | 33ms 发布计时器、5,000 点展示上限、30s 按设备时间保留、曲线 peak downsampling、Console 默认 2,000 blocks；不是无界曲线/无界文本控件 |

### 2.2 推测

- UI-09：GUI 线程每次快照合并全窗口数据、做包络选点，再更新隐藏页，可能耗尽 33ms 帧预算；未完成实时负载 p95 测量，不能写成已发生卡顿。
- UI-21：GUI 槽中等待线程/录制器退出可能产生长停顿；实际时长与负载、I/O 和线程退出情况有关，不能把每个 timeout 简单相加当作实际耗时。
- 字体替代、Qt 平台主题和多显示器 DPI 变化可能进一步放大文字/布局问题；不把离屏效果等同于原生桌面效果。

### 2.3 待确认与限制

- 已生成 2 种窗口尺寸 × 2 种模式 × 3 页 × 4 缩放共 48 张离屏图，另有 1920×1080 Live 图；人工重点检查三页 100% 及 Wi-Fi 200% 图，其余为渲染完成和尺寸检查，**不是全部逐像素验收通过**。
- 离屏 `QT_SCALE_FACTOR` 的 DPR 已实测为 1/1.25/1.5/2，但逻辑窗口尺寸仍为 1080×700 或 1440×900。它不模拟 Windows 工作区扣除任务栏、原生标题栏、多屏热切换或字体缩放。
- OpenGL 实际渲染、鼠标相机操作、读屏软件、系统高对比度、硬件错误/多节点持续采集、写盘性能、EXE 启动待验。所有模拟图数据来自确定性快照，不是实时设备读数。
- `docs/superpowers/specs/2026-08-31-host-ui-soft-metrics-kalman-design.md` 是历史方案，README 明确未实现。不得据此报告已存在 Kalman/软卡片；本计划不实施滤波。

## 3. 当前 UI 信息架构

```text
app.main -> _run_interactive -> MainWindow
├─ app_header：品牌 / CDC、WI-FI / 串口 / CONNECT或START LISTENER / REFRESH / 状态 / DISCONNECT
├─ acquisition_toolbar（所有Tab共享）
│  ├─ IIS3DWB名义采样率 / WINDOW 1、5、10、30s（默认10）
│  ├─ FIFO WM 128、256、511（默认256） / LIVE TARGET UART、CDC（初始UART）
│  └─ START / STOP / PAUSE（显示） / RECORD（所有会话）
└─ workspace_splitter
   ├─ 左侧
   │  ├─ WifiConnectionPanel（仅WI-FI）：网卡、预设IP、TCP/UDP端口、单播目标、帮助
   │  └─ NodeSidebar：节点列表 / 别名 / SAVE ALIAS
   └─ tabs
      ├─ LIVE MONITOR
      │  ├─ VibrationView：XYZ、AUTO Y、曲线/图例/坐标轴、采样率/点数
      │  ├─ OrientationView：模式、WAITING/LIVE/STALE、OpenGL或2D画布
      │  ├─ AttitudeView：8个指标（角度/加速度/模长/温度）
      │  └─ Stream Health：8个计数/速率/运行时间
      ├─ DIAGNOSTICS：滚动网格 PARSER / HOST / CONTROL STATE / FIRMWARE
      └─ CONSOLE：有限文本记录 / 命令输入 / SEND
```

没有自有菜单栏、工具窗、Dock、Dialog、表格历史页。pyqtgraph 和原生文本控件的默认右键菜单属于间接交互入口，需要运行检查；不应擅自删除。

主要操作路径：

- CDC 冷启动：REFRESH → 选择实际串口 → CONNECT（UUID、STATE、LIVESTREAM 只读查询）→ 明确节点 → 手动选 CDC → START。已有采集则 STOP → 等待 OK/IDLE → 切目标 → START。不能简化为自动串联命令。
- Wi-Fi：切 WI-FI → 网卡/预设 IP/端口/目标 → START LISTENER → 等待网关 → 选节点 → 手动控制。监听不是数据已就绪。
- 监视：Live → WINDOW/XYZ/AUTO Y → PAUSE 检视 → 恢复显示；Pause 不停止采集和记录。
- 记录：RECORD → 各节点按 UUID 独立文件，包含后到节点与重连分段 → 再点停止。它不是“只录制所选节点”。
- 历史导出：STOP/等 IDLE → 选节点 → Console 输入 AT+EXPORT=CDC 或 UART → 等终态；存入 exports。没有历史浏览/导入 GUI。
- 故障：Live 观察计数 → Diagnostics 明细 → Console 原始错误。当前恢复建议、关键错误与操作位置分离（UI-06）。
- 别名：选节点 → 输入 → SAVE ALIAS；须保持业务 1..64 字符与 UUID 持久化语义。

职责断点：全局 RECORD 与所选节点命令混排；监听状态和节点状态混用；当前节点不在主内容标题/Console 中确认；Pause 横跨所有快照而不是仅曲线，但命名未说明。

## 4. 设计基线与统一规则建议

以下为本次建议，不把审美选择包装成已存在缺陷；保留深色工程仪表盘、三 Tab、曲线主区域和已有 SPACE/COLORS。

| 类别 | 可执行规则 | 落点 |
|---|---|---|
| 字体 | 保留正文13、标题16、指标16、紧凑指标14；11仅用于次要标签，长值不靠缩小字体解决；正文Segoe UI/微软雅黑回退，数值Consolas；字体缺失要实测 | `P/theme.py`、`P/orientation_view.py` |
| 间距 | 复用 SPACE 4/8/12/16/24；表单标签到控件4、字段组8–12、卡片16；不添加第二套全局间距常量 | `P/spacing.py`、各 layout |
| 控件 | 输入/按钮最小逻辑高度32，统一边框6px圆角；QSpinBox 纳入同族；高度用 minimum/sizeHint，避免固定行高裁切；可点区域至少24×24逻辑像素 | `P/theme.py`、`P/controls.py` |
| 颜色 | 复用 COLORS；正文对面板目标≥4.5:1，焦点/边界目标≥3:1；由实际渲染背景测量，不宣称当前全部满足；错误必须带文本 | `P/theme.py` |
| 操作层级 | 当前主要连接/START使用一个primary角色；STOP、DISCONNECT保留清晰文字和危险语义，disabled不能仍呈鲜红可用外观；不强加STOP确认框延缓操作 | `P/main_window.py`、`P/theme.py` |
| 状态 | 分开显示“监听状态 / 所选节点及状态 / 设备报告状态 / 显示暂停 / 记录状态”；未知用—或UNKNOWN，不能替换为0或CONNECTED | 最小只读展示状态适配、`P/main_window.py` |
| 表单 | label buddy、明确字段名/端口范围提示、局部错误文本+定位焦点；后端server_config仍是校验权威；不更改合法范围和默认值 | `P/connection_view.py` |
| 数据卡片 | 字段名、数值、单位、所属节点及新鲜度可辨；完整精度可复制；不缩写掉精度以塞进一行 | Live/Diagnostics |
| 图标 | 优先现有QPainter或Qt标准图标；不用依赖特殊Unicode字形的暂停符号；图标配文本/accessibleName | `P/controls.py`、`P/main_window.py` |
| 反馈 | 操作区内非模态状态条；Console保留原始诊断；pending不表示成功，超时表示未确认，不能自动重发 | `app.py`、`P/main_window.py` |
| 术语 | 本轮保留英文界面并加必要操作解释；DISPLAY PAUSED、RECORD ALL、STOP ACQUISITION的范围清楚；语言全面切换待产品确认 | 各可见字符串、中文手册 |
| 小窗口 | 使用现有布局的分组换行/局部滚动，不通过全局缩放字体或隐藏STOP解决；侧栏可收起但有明确恢复入口 | `P/main_window.py`、`P/connection_view.py` |

轻量实现：继续在 `theme.py` 集中 colors/字体/状态选择器，在 `spacing.py` 管理间距；复用 IntegratedComboBox；只在状态去重确有必要时新增 `P/ui_state.py`（**拟新增，当前不存在**）承载只读投影。不要引入新的组件库或通用皮肤引擎。

## 5. 全局问题清单

优先级：P0误操作/核心不可用；P1核心流程或监控；P2效率/一致性/维护；P3低频增强。成本S=局部，M=单页或少量组件，L=跨页状态/验证。风险/依赖列中的阶段号对应第11章。UI展示状态的调整不得改变原有业务状态机。

| ID | 优先级 | 成本 | 证据状态 | 页面/区域 | 问题摘要 | 用户影响 | 涉及文件/符号 | 建议改法 | 不得改变的行为 | 验收要点 | 风险/依赖 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| UI-01 | P0 | M | 【已确认】代码+信号复现；实际设备误发未执行 | 节点/共享控制栏 | 离线节点可高亮但不发选择信号，控制器保留旧目标；selected_node_changed未接回UI | 以为操作A，实际可能操作B | `P/connection_view.py:NodeSidebar._emit_selected_node`；`P/app_controller.py:select_node/send_command/_on_thread_finished`；`app.py:_run_interactive` | 最小方案禁止离线行成为操作选择；事件回传用QSignalBlocker同步在线目标；详情和控制栏常显alias+UUID；每次启用命令前核对UI选中ID与控制器目标一致 | 控制器仍只路由所选在线节点；不自动发设备命令 | B在线→点击A离线→START/STOP/WM/CLI测试：A不得成为误导性高亮；显示目标与接收命令的fake transport一致；掉线自动替代与重连同步 | 阶段0先做；严禁只改标题掩盖错位 |
| UI-02 | P1 | M | 【已确认】 | 连接/工具栏 | set_wifi_server_state将监听当connected；无设备CONNECT无声返回；Console离线仍可发送 | 空操作/错误，难以理解就绪状态 | `P/main_window.py:set_connected/set_wifi_server_state/_emit_connect_requested`；`P/console_view.py` | 分离listener_running与selected_node_available；无节点禁用节点命令/RECORD并说明原因；监听停止入口仍可用；无串口禁用CONNECT+REFRESH指引 | CDC/Wi-Fi互斥、全局断开、后到节点录制保持 | 空串口、监听零节点、首次节点、全部节点掉线、停止监听矩阵逐一检查；无隐式命令 | 阶段2，依赖UI-01；不能误禁用STOP/断开收尾 |
| UI-03 | P1 | M | 【已确认】 | 全局PAUSE/Live/诊断 | controller不发布snapshot，VibrationView.set_paused没接线；姿态LIVE/诊断被冻结却无显著提示 | 冻结值被理解为实时；切节点时旧快照仍在 | `app.py`；`P/app_controller.py:set_display_paused/_publish_selected_session`；`P/vibration_view.py:set_paused` | 明示DISPLAY PAUSED/RESUME及“采集和记录继续”；对所有被冻结区加暂停标记；暂停切节点显示“该节点显示已暂停”而非旧节点值；仅复用现有暂停语义 | 不改变采集、记录、健康信号和暂停期间snapshot发布策略 | app真实接线测试暂停后数值不更新、host health仍可更新、fake采集/记录继续、恢复收最新快照；徽标可见 | 阶段2；双重暂停标志必须同步，不引入第二计时器 |
| UI-04 | P1 | M | 【已确认】 | 姿态/Live/诊断 | 断开不重置新鲜度；Diagnostics遇None不清旧status/control字段 | 旧设备数值被当作当前设备结果 | `P/main_window.py:set_connected/update_snapshot`；`P/diagnostics_view.py:update_snapshot`；`P/orientation_view.py` | 断开保留末值但显式OFFLINE/末次值；换节点先清该节点未知字段为—；快照None时清对应字段组；姿态数值与画布共享freshness文案 | 不清底层store/解析器/记录，不改0.5s姿态stale阈值 | A有状态→B无状态各字段为—；断开不能显示LIVE；重新连接不继承旧节点身份；暂停与offline优先级明确 | 阶段2；不要用0伪造正常计数 |
| UI-05 | P1 | M | 【已确认】代码路径 | 全局RECORD | 按钮立即checked；无session/文件启动失败不回传按钮状态；写盘failure仅在health；所有节点录制范围未明 | 用户误以为数据已保存 | `P/app_controller.py:set_recording/_start_session_recording`；`P/main_window.py`；`A/controller.py:health` | 增加只读录制结果投影（未启用/等待UUID/写入中/部分失败/失败）；展示成功节点数和实际批次路径；信号阻塞回写UI；失败不把“armed”意图说成成功 | 保留全局录制、后到节点、UUID等待、分段及原始字节；不得自动停止所有录制器或重试 | fake无节点/待UUID/启动OSError/队列失败/两节点部分失败；显示与实际recorder吻合；原始文件与基线一致 | 阶段2；最小controller信号适配，禁止借UI修写盘策略 |
| UI-06 | P1 | M | 【已确认】缺反馈；耗时程度待验 | 全局操作/错误 | 错误只转Console；无连接中/停止中提示；START/STOP不显示设备状态；目标500ms宽限不是确认 | 看不到失败、反复点击、误判命令完成 | `app.py:_run_interactive`；`P/main_window.py:_emit_livestream_requested/update_snapshot`；`P/app_controller.py` | 操作区增非模态错误条和Console未读标记；展示报告的acquisition_state及请求待确认；命令受理和固件确认分开；500ms保留为已有同步宽限，不当ACK；STOP保持可达 | 不改命令/查询顺序、默认目标、宽限值、重试策略；不凭OK猜多个请求归属 | 从Live触发校验错/ERROR:STATE/BUSY/断开，当前页可见原因；延迟响应显示未确认；无额外START/STOP/重发 | 阶段2；无请求ID时不伪造逐命令成功关联 |
| UI-07 | P1 | M | 【已确认】离屏截图 | Wi-Fi参数侧栏 | 参数区无滚动，在1080×700字段挤压、指导文字被截断 | 配网信息不完整，端口难操作 | `P/main_window.py:__init__`左侧layout；`P/connection_view.py:WifiConnectionPanel` | 参数卡内容加入可伸缩QScrollArea；字段组sizeHint保障；帮助可折叠但保留摘要；节点列表保有可操作高度；不压缩输入高度 | IPv4验证、端口1..65535、TCP54321/UDP12345不变 | 1080×700两模式及长网卡名；滚动可到所有字段、无标签重叠、列表与STOP可访问 | 阶段2；配合UI-10、UI-19，避免嵌套滚动陷阱 |
| UI-08 | P1 | L | 【已确认】最小尺寸事实；原生表现【待确认】 | 整窗/DPI | 最小1080×700逻辑像素，1080p/200%可用约960×540未扣标题任务栏；离屏成功不等于可放入屏幕 | 主要操作可能越出工作区 | `P/main_window.py:__init__`；`P/orientation_view.py:resizeEvent`；`app.py` | 根据availableGeometry限初始尺寸；先完成重排/滚动，再降低硬最小限制；建议可用内容960×500可达全部核心操作；较小工作区滚动兜底；不得手工乘DPI双缩放 | 不改变显示时间窗/样本/参数；保留Qt6缩放机制 | 第8章物理分辨率×系统缩放实测；标题/关闭/STOP/连接均在屏内；跨屏后无需重启 | 阶段4，依赖UI-07/19；不要仅把minSize改小 |
| UI-09 | P1 | M | 【推测】性能风险，调用链已确认 | 实时刷新 | GUI每33ms做snapshot全窗复制/包络；每次更新隐藏Live/诊断；导出检查也取snapshot | 高窗口长度或多节点下可能卡顿 | `P/app_controller.py:_publish_snapshots/_publish_selected_session/_finalize_completed_export`；`A/sample_store.py:snapshot`；`P/main_window.py:update_snapshot` | 先测回放负载；只在慢的展示端缓存最新快照、隐藏页延迟渲染、相同文本不重设；回页立即补最新；若数据层复制仍瓶颈另列最小只读接口适配 | 原始采集/包络算法/5000点/30s/记录均不动，不跳过CLI和export终态处理 | 1/10/30s、1/16节点模拟，记录p50/p95 UI回调和heartbeat；第7章预算；保存字节一致 | 阶段3先量后改；越界到store算法就暂停 |
| UI-10 | P2 | S | 【已确认】代码+截图 | Wi-Fi下拉/端口 | interface_combo是裸QComboBox，但全局QSS隐藏原箭头，仅IntegratedComboBox自己画箭头；QSpinBox未获输入样式 | 网卡选择缺发现性，输入高度不一致 | `P/connection_view.py:WifiConnectionPanel`；`P/theme.py`；`P/controls.py` | 网卡改用现有IntegratedComboBox；补QSpinBox输入、箭头、focus/disabled样式 | itemData和配置逻辑/端口范围不变 | 四DPR下箭头可见且点击/Alt+Down能展开；spin与lineedit高度一致，键盘增减仍工作 | 阶段1；QSS不得遮住spin上下按钮 |
| UI-11 | P2 | S | 【已确认】截图+选择器 | 全局视觉层级 | danger角色样式覆盖disabled观感，断开时STOP/DISCONNECT仍鲜红；primary不突出；card-actions继承深色背景 | 禁用状态难辨，注意力偏向不可用操作 | `P/theme.py:dark_stylesheet`；`P/main_window.py`；`P/vibration_view.py:header_actions` | 明确danger:disabled、pressed、focus选择器；primary只给主操作；card-actions透明；保留现有颜色 | 不改enabled逻辑或危险操作执行方式 | enabled/disabled/hover/pressed/focus截图成对比；断开按钮明确灰化；键盘焦点可见 | 阶段1；检查选择器优先级 |
| UI-12 | P2 | M | 【已确认】复现 | 节点别名/列表 | set_nodes全清重建覆盖未保存输入，空列表仍有可点保存 | 编辑丢失、保存失败不易定位 | `P/connection_view.py:NodeSidebar.set_nodes/_emit_alias_requested` | 按node_id就地更新；只有目标变化才载入别名，dirty输入保护；无节点禁用保存，校验信息就地展示1..64规则；刷新不额外发选择请求 | NodeSessionManager.set_alias规范化与QSettings键不变 | 输入草稿→录制/UUID节点更新→草稿保留；切节点规则明确；空白/64/65字符回归 | 阶段2；依赖UI-01，UUID替换时草稿不得移到其他节点 |
| UI-13 | P2 | M | 【已确认】 | Diagnostics | 大量全大写字段单长表；long last_error不换行且不可便捷复制；关键故障要向下找 | 查障慢，长UUID/错误占宽 | `P/diagnostics_view.py:_add_section/_replace_values` | 保留所有键，加入分区跳转/字段查找、错误区摘要；值可选择复制，长错误换行，协议字段原名留tooltip；范围单位注释来自协议 | 不重命名数据字段，不删reserved uart_credit_bytes，不改None/数字 | 长错误300字符/完整UUID/uint64值不被隐藏；搜索定位；全部现有字段仍可查看 | 阶段3；与UI-04清旧值一起验证 |
| UI-14 | P2 | M | 【已确认】功能缺口；自动滚动行为【待确认】 | Console | 只有类别无时间/检索/清空入口；2000 blocks受限但单条长度和每帧追加批次未控 | 追溯、定位与历史阅读效率低 | `P/console_view.py:_append`；`P/app_controller.py:_publish_snapshots` | 为展示记录加接收时间/类别；搜索、复制、仅清显示、跟随末尾开关；保留当前block上限；长内容可展开/复制完整原文；批量UI插入前先量负载 | 不更改发送文本、协议响应原文、底层记录格式；不静默截断需保留的原始信息 | 注入2500行、长响应、用户滚到中段后再追加；查找/复制正确、跟随关闭不抢位置、block≤2000 | 阶段3；Qt默认复制菜单先验再增；不添加新无界缓存 |
| UI-15 | P2 | M | 【已确认】 | Console多节点 | 响应排空所有session却只emit所选节点；旧Console文本无节点来源 | 切节点后混淆响应归属，非选中节点问题无上下文 | `P/app_controller.py:_publish_snapshots`；`P/console_view.py` | 最小新增展示信号携带node_id/alias/接收时间；若保留全节点日志必须用一个总容量预算并标来源/筛选；默认只看所选，切换分隔线 | 不改变响应解析和命令路由，不把未选节点响应当当前设备ACK | A/B交错响应+切换后能正确归属；原始RX内容不变；总展示缓存有限 | 阶段3，依赖UI-01；展示接口变更需app接线回归 |
| UI-16 | P2 | M | 【已确认】仅AUTO Y；平移体验【待确认】 | 振动图 | 有鼠标XY操作/图例/限点，但无明确恢复时间范围入口；暂停概念在工具栏 | 缩放后不知如何回实时范围 | `P/vibration_view.py` | 加RESET VIEW/FOLLOW状态，重置x到当前window负值..0、y复用AUTO Y；说明x是相对最新采样时间，手动浏览用DISPLAY PAUSE；不得声称保存绝对历史 | 不改snapshot时间轴、原始数据/包络、单位和峰值 | 选10s→缩放/平移→reset回[-10,0]；AUTO Y开关可预测；暂停不回拉；恢复取最新 | 阶段3；pyqtgraph默认右键菜单行为先记录 |
| UI-17 | P2 | S | 【已确认】 | Stream Health/姿态新鲜度 | 未收到status时drop/error显示0；姿态数值没有STALE；8格权重一致、无错误解释 | “未知”被误认为无错误，难识别数据损失 | `P/main_window.py:update_snapshot/_create_live_tab`；`P/orientation_view.py:AttitudeView` | 未知来源用—，有证据的0保留；异常计数加文字/图标和详情入口，复制完整值；姿态与画布共享WAITING/STALE说明 | 不改计数定义、LINK ERR CDC/UART选择、阈值或告警逻辑；颜色仅展示强调 | status=None与全零分别验证；非零显示可辨且值完全一致；stale不把数值改零 | 阶段3；不按本计划新增业务告警阈值 |
| UI-18 | P2 | M | 【已确认】缺显式配置；实际键盘/读屏【待确认】 | 全局可访问性 | label无buddy、无显式Tab顺序/焦点样式；Pause特殊字形在离屏图显示方框 | 键盘/读屏及字形可读性不足 | `P/main_window.py`、`connection_view.py`、`console_view.py`、`theme.py` | 表单setBuddy/accessibleName；定义稳定Tab顺序；Space操作按钮，Enter限定当前表单；暂停用文本或绘制图标；图例辅以文字，不仅颜色 | 不增加容易误触的全局START/STOP快捷键、不截获Console Enter | 纯键盘连接配置/切页/选节点/发命令；焦点全程可见；关闭菜单Esc不触发设备命令；读屏正确读字段 | 阶段4；不得因focus样式改变控件几何 |
| UI-19 | P2 | M | 【已确认】布局逻辑；极值溢出待验 | Live紧凑布局 | Attitude仅按整窗高度<800变4列，不看所在宽度；健康8格固定一行 | 拖窄右区/长值可能挤压，短窗并不总适合4列 | `P/orientation_view.py:AttitudeView.resizeEvent/_apply_layout`；`P/main_window.py:_create_live_tab` | 根据该卡可用宽度及sizeHint选列数；健康宽度不足换4×2；窄图卡header actions换第二行；不锁死7:3比例 | 8项指标、符号、小数两位、完整计数不变 | 拖splitter到边界、正负长值、最大计数、宽短/窄高窗口；标签不重叠，控件可恢复 | 阶段2；布局测试从硬列数转可见性+内容完整性 |
| UI-20 | P2 | M | 【已确认】 | 验证资产 | baseline与当前入口不符；测试有单widget暂停但无app暂停联动；无DPI矩阵 | 测试绿仍漏状态/布局回归 | `tests/test_widgets.py`、`test_app_smoke.py`、`test_connection_widgets.py`；`tools/capture_visual_baseline.py`；visual manifest | 先保留旧图作历史，扩截图工具参数支持page/mode/size/state；新基线按场景审阅后替换；增加目标/暂停/错误接线用例 | 禁止通过删业务断言让测试变绿；不把离屏当硬件通过 | 每个P0/P1有测试/人工证据映射；截图节点/连接/数据状态自洽，不再connected却无节点 | 阶段0建立，阶段5收口 |
| UI-21 | P2 | M | 【推测】卡顿程度；同步等待已确认 | 断开/停止记录/退出 | GUI路径thread.wait、wake.join、recorder.stop等待I/O；无停止中反馈 | 窗口可能暂时无响应 | `P/app_controller.py:disconnect_device/_stop_wifi_resources/_stop_session_recording`；`S/recorder.py:stop` | 首先测fake慢退出；显示停止中并阻止重复提交；若达卡顿门槛，独立最小异步收尾适配，保留退出顺序/timeout/对象所属线程 | 不改close、quit、wait、finalize语义；不能terminate线程或提前清对象 | 慢writer/transport退出、超时、关闭窗口时检查错误可见、元数据完整、无存活线程；超时原样报告 | 阶段5需独立审核；仅画loading无法解决主线程阻塞 |
| UI-22 | P2 | S | 【已确认】渲染和代码 | 图表单位/3D语义 | 数据g而轴自动SI前缀显示mg；模式名占显著位置，向前/加速度箭头没有文字说明 | 可能误读倍率或把朝向当位置 | `P/vibration_view.py:__init__`；`P/orientation_view.py:_install_opengl/_FallbackCanvas` | 解释轴前缀和原始g单位；以当前显示倍率正确读值，不强制改原单位；姿态加轴/箭头说明与“姿态，非位移”提示；回退原因放tooltip | 旋转ZYX、world_acceleration、原始精度与缩放不变 | 0.001g显示与当前轴对应，数值卡g不变；yaw90°方向回归；2D/3D说明一致 | 阶段3；这是理解性改善，不是确认单位算法错误 |
| UI-23 | P3 | S | 【已确认】入口仅Console | 导出/帮助 | 导出操作与手册依赖强，无就近指引 | 低频用户需外找步骤/路径 | `P/console_view.py`；`docs/USER_MANUAL_zh-CN.md` | Console加可折叠只读操作指引及当前导出phase/保存位置说明；只显示已知路径，不伪造进度百分比 | 不一键串联STOP/EXPORT/START，不修改导出格式或重复容忍 | 从指引完成手动路径，EMPTY/COMPLETE/ABORTED显示正确，所有命令仍由用户发起 | 阶段3；新导出向导另立项 |
| UI-24 | P3 | S | 【已确认】无持久化 | Splitter/窗口 | 布局每次恢复固定尺寸，拖到折叠后缺明确reset入口 | 重复调整，内容恢复难发现 | `P/main_window.py`；`P/splitter.py`；`app.py` | 提供RESET LAYOUT；可选QSettings新增ui/布局键并校验可用屏幕，非法状态回默认；保留可拖动性 | 不动aliases/*及wifi/*旧键，不动设备配置 | 拖窄/折叠→reset可恢复；重启/换屏不出屏；旧配置照常读取 | 阶段4；先reset，再决定是否持久化 |

## 6. 逐页审查

全页均完成源代码审查和离屏构造；Live、Diagnostics、Console 都有截图。未做原生桌面或硬件交互验收。以下引用问题 ID 的全部字段以第5章为准。

### 6.1 主窗口连接区与共享操作栏

- 入口与任务：启动立即可见；选择通路、连接、参数、采集、显示暂停、全局记录。
- 布局：两条单行 QHBoxLayout，主窗口1440×900，最小1080×700；连接设备框最小250，状态最小110，工具栏最小50高。
- 视觉：STOP/DISCONNECT禁用仍红（UI-11）；实际采集状态不在主栏（UI-06）；传感器名义26.667kHz与实测samples/s需区分（UI-17/22）。
- 缩放：多控件固定一排，长LISTENING地址与较小工作区有宽度风险（UI-08）；不允许压缩到读不清。
- 交互：监听/节点就绪混用（UI-02），错误跨Tab（UI-06），录制范围与成功状态不清（UI-05），目标可能错位（UI-01）。没有连接/停止中的完整展示状态。
- 一致性：设定值、请求值和设备报告值要分开。WM当前只发送，没有按status.watermark_words回显；纳入UI-06，同样只读回显且阻塞信号，不增加查询。
- 涉及：`P/main_window.py`全部创建/状态函数、`app.py`接线、`P/app_controller.py`相关槽。
- 建议：按UI-01/02/05/06增加紧凑状态摘要，不再添加整条巨大信息栏；小窗口允许两行分组，STOP保持首屏可达。
- 保留：连接只读、手动控制顺序、默认10s/256/UART、全局记录和全局断开。
- 页面验收：无设备→监听→在线→采集→暂停→录制错误→断开逐状态截图；fake命令逐字节和目标比较；不因程序回显发送命令。

### 6.2 Wi-Fi 参数区

- 入口与任务：选择WI-FI后显示，构造WifiServerConfig；网卡发现来自Qt，不打开设备。
- 组件：网卡Combo、预设IP LineEdit、两个SpinBox、单播目标LineEdit、指导Label。
- 视觉/一致性：裸Combo箭头被主题隐藏，SpinBox没有输入族样式（UI-10）；标签太长、没有buddy（UI-18）。
- 布局：无滚动容器，1080×700截图已出现内容挤压（UI-07）；长网卡名需省略显示+完整tooltip，不更改itemData。
- 状态：server_config合法性完整交给WifiServerConfig；错误只入Console（UI-06）。自动复制IP仅在预设为空时执行，切网卡不覆盖非空输入是现有行为，不能当错误强改。
- 数据/日志：没有实时曲线；错误仍保留Console原始详情。
- 涉及：`P/connection_view.py:WifiConnectionPanel`、`P/main_window.py:_emit_connect_requested`、`transport/gateway.py:WifiServerConfig`。
- 建议/保留：UI-07/10/18及局部错误定位；保持网卡选择、预设IP匹配、单播列表拆分、QSettings恢复规则。
- 验收：无网卡、IP不匹配、非法单播、端口1/65535、长名称、旧配置；正确值构造的config与原版本完全相同。

### 6.3 节点列表与别名

- 入口与任务：所有Tab左侧；最多16个在线Wi-Fi session的导航，离线/重连项仍可能显示。
- 组件：QListWidget多行文本（alias、uuid后8位、peer、状态、REC、!），别名输入与SAVE ALIAS。
- 视觉：!无原因说明，长alias/peer应tooltip；当前目标不在详情重复确认（UI-01/15）。
- 布局：Wi-Fi配网区占高，节点列表被压缩；优先保证列表至少可见一项且滚动（UI-07）。
- 状态：离线行可高亮但不改变实际目标（UI-01）；clear重建导致编辑丢失（UI-12）。这是当前P0修复落点。
- 一致性：使用NodeSummary的状态文本，不能自行把CONNECTED推断为STREAMING；当前session manager并未随传感数据自动设置STREAMING。
- 涉及：`NodeSidebar`、`NodeSessionManager`、`AppController.selected_node_changed/_emit_nodes/_on_thread_finished`。
- 建议/保留：就地更新行、同步操作目标、离线信息只供查看不作为命令目标；保持UUID绑定、重复UUID拒绝、别名规范化和重连身份规则。
- 验收：A/B切换、选离线、掉线替代、UUID到达、更名保存失败、16节点滚动、未保存输入保护；每次命令目标等于明确显示的目标。

### 6.4 LIVE MONITOR—振动

- 入口与任务：默认Tab主要区域，三轴实时波形与范围检视。
- 组件：PlotWidget、XY鼠标操作、legend、XYZ复选、AUTO Y、rate_label、未接线paused_badge。
- 视觉：高密度三曲线叠加时蓝线覆盖感强；这是样本叠加现象，不证明数据错误。图例和轴字较小、图例处于曲线内（UI-16/22）。
- 布局：标题和固定sizePolicy的操作行在小宽度抢空间（UI-19）；不以缩小标题/按钮作为唯一处理。
- 状态：无数据只有0 samples/s；连接后无数据需要说明检查设备报告状态/输出目标，不能擅自自动START；暂停未显示、断开保留旧图（UI-03/04/06）。
- 一致性：轴g会自动呈mg，要解释倍率，不修改数据；XYZ标签存在，但颜色相近视觉场景可增加线型区分，先做可读性对比，不默认加每点符号。
- 实时：已有clip、peak downsample、5000点；UI端setData三次，不能按26.667kHz逐控件刷新（UI-09）。
- 涉及：`P/vibration_view.py`、`MainWindow.update_snapshot`、`AppController._publish_selected_session`。
- 建议/保留：UI-03/04/09/16/19/22；维持g数值、相对时间、包络选点、原始保存。
- 验收：空数组、满5000点、三轴隐藏组合、30s、缩放恢复、暂停恢复、断开、换节点、隐藏页回页；原始曲线数组应与基线相同。

### 6.5 LIVE MONITOR—姿态画布

- 入口与任务：右上；观察设备朝向及世界坐标加速度箭头，不提供位置解算。
- 组件：OPENGL 3D/2D FALLBACK标签、WAITING/LIVE/STALE标签、GLViewWidget或_FallbackCanvas。
- 视觉：渲染模式与新鲜度同排，轴/箭头缺文字解释（UI-22）；2D等待文本存在，GL无数据状态主要靠WAITING文字，不能称全无empty状态。
- 布局：fallback最小180高，小窗口与下方指标竞争（UI-19/08）。
- 状态：stale阈值0.5s已有；快照冻结/断开不再调用update_snapshot时仍显示LIVE（UI-03/04）。
- 一致性：numeric卡必须同样说明stale；回退原因已有fallback_reason但用户看不到详细原因，宜tooltip。
- 涉及：`P/orientation_view.py:OrientationView/_FallbackCanvas/rotation_matrix_zyx/world_acceleration`。
- 建议/保留：只改状态说明/布局，保持ZYX旋转、相机初始参数及GL优先和异常回退分支。
- 验收：waiting、age>0.5、暂停、断开、yaw90°；原生GL和强制fallback分别验证，鼠标操作不被新增提示层吞掉。

### 6.6 LIVE MONITOR—数值与Stream Health

- 入口与任务：右下八个姿态数值和底部八个健康值；查看角度、g、温度、接收速率、CRC/丢包/链路/运行时长。
- 布局：数值默认2列×4，短窗变4×2；健康固定一行八格。旧规范写七格，当前实际为八格，应以当前代码为准。
- 视觉：数值格式`+.2f`已一致；健康标题11px、错误计数无非零强调；未知部分被呈0（UI-17）。
- 缩放：以整个窗口高度决定姿态列数，不考虑右卡宽（UI-19）；长运行时间/uint64须完整可达，不能擅改精度或K/M缩写。
- 状态：姿态数值没有age提示，断开末值和实时值外观一样（UI-04）。
- 涉及：`AttitudeView`、`MainWindow._create_live_tab/update_snapshot`。
- 建议/保留：UI-17/19；现有字段/单位/算法全部保留；异常颜色只是重复已有计数含义，不新增告警阈值。
- 验收：None、零、正负极值、长计数、stale、拖窄分隔器；当前LINK ERR随物理通路取cdc_errors/uart_dma_errors规则不变。

### 6.7 DIAGNOSTICS

- 入口与任务：第二Tab；逐项查看解析、主机、控制状态和固件计数。
- 组件：已有QScrollArea、固定创建的QLabel网格；不是每帧新建控件。
- 视觉：技术字段全大写长列表，重要错误与大量低频计数同权重（UI-13）；reserved注释已有，应保留。
- 布局：可滚动是优点；错误值不wordWrap、不可选中（UI-13）。
- 状态：None不清旧字段（UI-04）；Pause时snapshot部分冻结、HOST health继续更新，必须清楚分组标记（UI-03）。
- 一致性：保留协议原字段名作为定位信息，增加用户说明而不替换字段定义。
- 实时：隐藏Tab也收update_snapshot/asdict/_replace_values（UI-09）；可以保留最新快照延迟绘制，但不能停止健康/导出处理。
- 涉及：`P/diagnostics_view.py`、`UiSnapshot/AcquisitionHealth/FirmwareControlState`。
- 建议/保留：UI-04/09/13；不删任何字段，不把reserved 0报故障。
- 验收：所有字段可达、值可复制、超长last_error、节点切换None清空、暂停标记；滚动位置在刷新时不重置。

### 6.8 CONSOLE与导出相关反馈

- 入口与任务：第三Tab；发高级AT命令、看原始回复、手动归档导出。
- 组件：QPlainTextEdit readOnly、maximumBlockCount=2000、输入、SEND；无自有确认/进度弹窗。
- 视觉：类别TX/RX/ERROR文本与颜色共存，是已有优点；不是只依靠颜色。缺时间和节点来源（UI-14/15）。
- 布局：文本主区空间充分；长placeholder中命令是提示不是交互按钮，小窗需保留可读的简要说明。
- 状态：离线SEND可用、提交前就清空输入、错误在日志中；建议无目标禁用并说明，失败保留可恢复输入但不自动重发（UI-02/06）。
- 一致性：应用错误集中此处但其它Tab不知有错；需未读/状态条。复制已可使用原生文本行为，新增功能前先验证现有右键菜单。
- 实时：2,000 blocks不等于响应队列有界，也不等于单行字节有界（UI-14）；非所选节点响应被排空但不展示（UI-15）。
- 涉及：`ConsoleView`、`AppController.send_command_to/_publish_snapshots/_start_archive_recording/_finalize_completed_export`。
- 建议/保留：UI-14/15/23；不新增自动命令向导、命令纠错或自动确认危险AT操作。显示导出终态与位置，未知总量不显示假百分比。
- 验收：空命令、非ASCII、94/95字节、ENTER、选择切换、错误、EXPORT_EMPTY/COMPLETE/ABORTED；命令入队与CRLF输出逐字节保持。

## 7. 实时数据、图表与日志专项

### 7.1 已确认链路与保护边界

```text
Transport.read -> AcquisitionWorker(QThread) -> AcquisitionController.run
  -> StreamParser -> RealtimeSampleStore(锁+30秒保留)
  -> 原始完整帧 -> Recorder（独立写入，不经过UI曲线）
GUI QTimer 33ms -> 排空身份/CLI/导出终态 -> selected session.snapshot(window, 5000)
  -> snapshot_ready -> MainWindow -> 曲线/姿态/数值/诊断
GUI QTimer 5000ms -> 各session只读STATE查询
```

采集与UI频率已经解耦；没有证据表明采集worker直接setText或setData。跨线程QObject生命周期和lambda槽绑定仍需UI-21压力验证，不能泛称“线程安全全部通过”。

Pause停止snapshot_ready，health_ready仍发布，CLI和export收尾仍处理。整改必须先保持这个合同；如果将来希望“只暂停曲线、诊断继续更新”，那是行为改变，另行决策。

### 7.2 可执行方案

- UI-03/04/17：区分WAITING（未收到）、DISPLAY PAUSED（人为冻结）、STALE（现有姿态年龄规则）、OFFLINE（连接不在）；IIS当前没有独立最后到达时间字段，不得仅凭sample_rate仍非零认定实时。若增加IIS接收时间，仅作只读元数据适配，不改时间戳/采样计算；阈值需确认。
- UI-16/22：明确相对时间窗和自动SI前缀；RESET VIEW可恢复x时间窗；鼠标平移仍用已有pyqtgraph能力；不用截图推断实际频谱或振动峰值错误。
- UI-09：先记录`_publish_snapshots`总耗时、snapshot耗时、三个setData耗时、隐藏页更新耗时。优化从GUI少绘制开始；不得为了降低CPU丢原始记录帧、修改采样率、扩大/縮小记录范围。
- UI-14/15：以有限展示缓冲保存时间/节点/级别/原文；搜索和过滤只是投影；不得为每个节点另建无界日志。默认最大blocks继续2,000。所有节点响应可展示的新增路径需保持控制解析先完成，长日志不要影响命令反馈状态。
- 日志导出不是当前功能；先完成搜索、复制、跟随、清显示。若新增“导出日志”，必须单独明示为UI日志文本、用户选择路径，不与SDF1/JSON业务保存混同，不修改现有文件。

### 7.3 性能验收方法（新增测量，不冒充本轮结果）

固定机器/Qt版本，使用fake transport和合成单调设备时间，速率26,667 IIS样本/s，1/10/30s窗口；1节点和16会话分别运行30分钟（16节点总负载明确记录，不将所有通道等同单节点性能）。每次记录UI回调耗时p50/p95、GUI heartbeat最大延迟、进程RSS、曲线点数、队列水位与原始文件大小/hash。

建议阶段门槛：单节点GUI回调p95≤33ms；常用点击可见反馈≤200ms；30分钟内无持续>500ms交互停顿；曲线每轴≤5,000点，文本block≤2,000；初始保留窗口装满后不出现随时间单调增长的UI记录数。RSS比较第5/15/30分钟，若仍明显线性增长必须定位，不能仅用一次内存截图判泄漏。16节点门槛先记基线：任何改造不得降低采集/记录完整性或使UI时延较基线恶化超过10%；不达单节点门槛必须修复/明确标未通过，不能改测试阈值放行。

现有`tests/test_replay_performance.py`仅证明约2MB解析耗时<5s，**不证明GUI帧率**。补测时遵循UI-09先量后改；慢的底层算法不是本轮可自由替换的对象。

## 8. DPI、缩放、分辨率与可访问性专项

### 8.1 固定尺寸清单

| 定位 | 当前值/方式 | 判断与改法 |
|---|---|---|
| MainWindow构造 | 默认1440×900，minimum1080×700 | 逻辑像素；工作区适配UI-08 |
| MainWindow header | device min250，badge min110，水平单行 | 长设备/监听地址须省略+tooltip、分组重排 |
| toolbar | min50高，combo min72；单行全部操作 | 不使用固定高度承载换行，按sizeHint增长 |
| tabBar | fixed38高，8×18 padding | 默认语言可用；字体缩放必须验证sizeHint，不盲保固定值 |
| card title / divider | 3×20、1×22固定 | 装饰逻辑像素通常可保留，不是绝对坐标布局缺陷 |
| CapsuleSplitter | hit12，capsule4×48 | 已有大于可见线的命中区域；保留，补reset路径 |
| fallback | min180高 | 与短工作区冲突时由容器滚动或重排解决 |
| AttitudeView | 整窗height<800切4列 | 改为卡片可用宽度/高度可行性，UI-19 |
| theme | 11/12/13/14/16px字体、输入minimum32 | Qt逻辑尺寸不直接等同物理像素；不能统一乘devicePixelRatio |
| IntegratedComboBox | 绘制chevron right-12，8宽，pen1.4 | 向量绘制，分数缩放清晰度待原生检查，不需位图放大 |

没有发现自有QWidget.setGeometry绝对坐标页面；主要风险来自layout最小尺寸、固定行和缺滚动，而非“全部绝对布局”。

### 8.2 测试矩阵

| 物理屏幕 | 100% | 125% | 150% | 200% | 每格操作与判据 |
|---|---|---|---|---|---|
| 1366×768 | 1366×768 | 约1093×614 | 约911×512 | 683×384 | 扣任务栏后的availableGeometry为准；默认/最大化/最小，CDC和Wi-Fi三页；小到无法并列时滚动/收起，STOP/退出仍可达 |
| 1920×1080 | 1920×1080 | 1536×864 | 1280×720 | 960×540 | 重点发布矩阵；不能强制1080×700越出屏幕；全部字段经滚动可达 |
| 2560×1440 | 2560×1440 | 2048×1152 | 约1707×960 | 1280×720 | 文本不截、曲线/姿态清晰、最大化利用空间，窄分隔器可恢复 |
| 3840×2160 | 3840×2160 | 3072×1728 | 2560×1440 | 1920×1080 | 控件未双重缩放，鼠标命中与画面一致，GL/2D均验 |

表中数值是未扣标题/任务栏的近似逻辑屏幕尺寸，**不是当前已通过结果**。补充175%边界抽测，符合参考提示要求；本轮没有做175%离屏运行。

每格保存：系统显示设置、availableGeometry、DPR、窗口geometry、模式/页、空/在线模拟/错误状态截图。验收：无覆盖/重叠；文本可读；完整字段能通过滚动/复制查看；主要动作可达；最大化/还原无丢布局；打开下拉菜单不得超屏；字体放大不产生只有鼠标才能绕过的障碍。

多屏补充：100%与150%、100%与200%往返拖动；第二屏移除再启动；任务栏不同位置；窗口曾存于已移除屏幕；GL上下文和画布正确刷新。原生运行由Qoder在无设备模拟窗口进行，不使用真实transport工厂。

可访问性：为输入字段setBuddy/accessibleName；Tab依次到模式、设备/配置、连接、节点、工具栏、Tab内容；非模态错误可聚焦且不吞Console Enter；焦点/hover/disabled/pressed状态独立可辨；文本与符号共同指示状态。颜色对比按最终实际背景测量，Windows高对比度/读屏单独人工验收，不凭QSS颜色值宣布通过。

## 9. UI 技术债

此表复用问题ID，不新增计数；只处理与UI体验直接相关的部分。

| ID | 技术债 | UI影响 | 证据 | 最小改造方案 | 涉及文件 | 风险 | 回归检查 |
|---|---|---|---|---|---|---|---|
| UI-01/02/03/05/06 | UI状态散在控件、controller和snapshot | 目标/就绪/录制/暂停不一致 | 多个setEnabled/setChecked、未接selected_node_changed | 一份只读状态投影和单向apply；QSignalBlocker避免回写命令；必要时拟增ui_state.py | main_window/app_controller/app | 状态适配变相重写业务 | fake状态矩阵与命令序列 |
| UI-10/11/18 | 新控件未进入现有主题，状态选择器不完整 | 缺箭头、矮输入、禁用像可用 | 裸Combo/Spin与theme选择器 | 复用IntegratedComboBox、补QSS角色 | connection_view/theme/controls | 样式改变sizeHint | 全DPR控件状态截图 |
| UI-12 | 列表clear重建与编辑绑定 | 草稿被覆盖、重复selection | set_nodes | 按ID差量更新+dirty编辑状态 | connection_view | UUID变化和重连误保留 | UUID替换、编辑中新增节点 |
| UI-04 | 仅增量替换诊断值无缺失组处理 | 跨节点残值 | update_snapshot有None跳过 | 按来源组reset，再只读更新 | diagnostics/main_window | 正常末值误清 | None、切换、断开、暂停 |
| UI-09 | 渲染/数据整理集中GUI timer | 可能拖慢操作 | snapshot调用与隐藏页更新 | 测量后仅节流绘制，保留业务消费路径 | app_controller/main_window各view | 漏export终态/错过最新值 | 持续回放+导出终态 |
| UI-14/15 | 字符串日志没有来源元数据 | 多节点追溯困难 | cli_response(str) | 添加有界展示事件，保留旧协议字符串 | app_controller/console/app | 新缓冲无界、错误归属 | 交错节点、容量和原文 |
| UI-19/24 | 布局依赖整窗固定阈值/比例 | 窄卡拥挤，折叠难恢复 | resizeEvent与setSizes | 根据卡片sizeHint重排，reset layout | main_window/orientation/splitter | 递归resize抖动 | 连续拖动+极值文本 |
| UI-20 | 黄金图与现有代码偏离，UI测试多为结构断言 | 假绿 | 旧PNG、单widget暂停测试 | 补接线行为、状态截图矩阵 | tests/tools | 无审阅覆盖旧基线 | 人工签署每种截图 |
| UI-21 | GUI执行阻塞收尾 | 潜在退出冻结 | thread.wait/recorder.stop | 先测后独立适配，不大拆controller | app_controller/recorder调用处 | 资源释放/录制元数据受损 | 超时、取消、重复关闭、无线掉线 |

## 10. 业务逻辑保护清单

| 保护项 | 当前实现定位 | UI改造允许做什么 | 明确禁止改变什么 | 回归验证 |
|---|---|---|---|---|
| SDF1帧/CRC/版本/序列 | `protocol/sdf1.py:StreamParser`及`docs/PROTOCOL.md` | 展示计数/错误来源 | 帧结构、CRC、序列/归档标志解析、容错语义 | `test_protocol.py`、`test_protocol_golden.py`、golden bin |
| CLI及换行 | `A/controller.py:enqueue_command`；`transport/cdc_serial.py:write_control`；`gateway.py:AcceptedSocketTransport.write_control` | 局部显示校验错误，保留输入供修改 | 1..94 ASCII无NUL、strip、CRLF、命令字和发送顺序 | `test_acquisition_controller.py`、`test_transport.py`、`test_gateway_transport.py` |
| 连接查询与手动控制 | `AppController._add_session`；`app._set_and_query_livestream`；`AcquisitionController.start_acquisition/stop_acquisition` | 状态投影、控件回显时阻塞信号 | 查询依次UUID→STATE→LIVESTREAM；禁止连接自动START/STOP/选CDC；用户改目标仍set再query；不得自动重试 | `test_app_smoke.py`对应requests_status、selected_node和wiring测试；fake命令完整序列 |
| 通道/默认参数 | `MainWindow._create_acquisition_toolbar`；`AcquisitionController.set_watermark/set_livestream` | 增说明、报告值回显 | WINDOW1/5/10/30默认10；WM128/256/511默认256；初始UART；500ms宽限 | widget默认值和信号次数；invalid watermark/target测试 |
| Wi-Fi网络行为 | `WifiServerConfig/GatewayListener/UdpWakeService`；`AppController.start_wifi_server` | 配置布局、原校验错误定位 | TCP54321/UDP12345、2s唤醒、IP匹配、16会话容量、CDC互斥、网络重连含义 | `test_gateway_transport.py`、`test_app_smoke.py` listener/capacity/reconnect |
| 节点身份/路由 | `A/sessions.py:NodeSessionManager`；`AppController.send_command_to` | 同步UI操作目标、禁离线操作、显示身份 | UUID绑定/重复拒绝、别名1..64与strip、所选节点唯一命令目标 | `test_node_sessions.py`及A/B误选回归 |
| 数据解码/单位 | `protocol/sdf1.py:IisTimestampReconstructor/_decode_jy61pl` | 解释轴前缀和单位，显示原值 | IIS换算、JY16/32768和180/32768、温度换算、校准/精度 | golden解码数值；`test_protocol.py` |
| 姿态计算 | `P/orientation_view.py:rotation_matrix_zyx/world_acceleration/AttitudeView.update_snapshot` | 布局、文字/新鲜度 | ZYX、加速度模长、符号+.2f、g/deg/°C、0.5s stale | `test_orientation.py`及numeric快照 |
| 展示与采集分离 | `A/sample_store.py`；`AppController`两个timer | 缓存只读最新展示值、隐藏页延迟绘制 | 30s保留、5000点、包络选点、采样时间/速率计算、pause不停止采集/记录 | `test_sample_store.py`和app暂停接线测试 |
| 原始记录与归档 | `S/recorder.py`；`AppController._start_session_recording/_start_archive_recording/_finalize_completed_export`；`A/controller.py:_handle_frame` | 只读显示路径/成功/失败/phase | 原始完整帧、4MiB容量策略、metadata键、UUID目录、segment命名、实时与archive隔离、export_revision终态判定 | `test_recorder_replay.py`、`test_app_smoke.py` global/reconnect/export、`test_realtime_archive_acceptance.py` |
| 存储路径/配置兼容 | `S/paths.py:data_root`；AppController QSettings；`WifiConnectionPanel.restore_settings` | 新ui/*布局键；只读显示保存位置 | SENSOR_HOST_DATA_DIR、%LOCALAPPDATA%/SensorHost、OpenAI/STM32SensorHost、aliases/*、wifi/*键及类型 | `test_data_paths.py`、`test_connection_widgets.py`；旧配置fixture |
| 生命周期 | `AcquisitionWorker`、`AppController.disconnect_device/_stop_wifi_resources`；`S/recorder.py:stop`；`app.aboutToQuit` | 进度说明；必要时独立最小非阻塞适配 | stop_event/transport.close/thread退出/record finalize顺序、超时与错误、对象所属线程；禁止强杀 | `test_app_smoke.py` worker/lost/queued client；fake慢退出；无存活线程/文件句柄 |
| 告警/安全 | `NodeSummary.alert`、`AcquisitionHealth`、firmware控制响应 | 展示现有错误/计数，明确设备状态 | 不新增或改告警阈值、设备联锁、安全限制，不自行推断IDLE或EXPORT可操作性 | 故障响应原样可见；未知显示未知；原始ERROR/计数一致 |
| 权限/外部接口 | 【已确认】当前自有UI未发现登录/权限页或插件入口；设备端权限/联锁【待确认】 | 本轮不增加权限系统 | 不把“没找到UI”当作设备没有安全限制，不改变入口/包名/API行为 | 原命令拒绝仍可见；`test_package.py/test_packaging.py` |

接口适配必须单列变更：新增只读信号/展示对象，不向设备层写UI状态；旧输入输出保持。若需要改变store或资源收尾，先记录原输入输出、测试基线和依赖，再做独立小改，不允许顺手全面重构。

## 11. 分阶段执行计划

### 11.0 通用执行与验收合同

Qoder可采用 executing-plans 的逐项执行方式；本任务只授权计划内单阶段工作，不要求并行代理。每个阶段单独差异、构建/运行证据、人工验收、回滚点。用户确认该阶段结果前不跨阶段继续。

从项目根目录运行以下已核验入口；路径失效先记录差异，不猜测替换环境：

```powershell
Set-Location D:\Codes\SensorHost
$env:QT_QPA_PLATFORM='offscreen'
& .\.venv\Scripts\python.exe -m pytest tests -q
& .\.venv\Scripts\python.exe -m compileall -q src tools
& .\.venv\Scripts\python.exe -m sensor_host.app --smoke-test
git diff --check
```

预期全部退出0，测试无新增失败/跳过GUI。172是本轮基线数量；新增测试后不锁定为172，不允许通过跳过测试保数量。UI行为修改应先加能失败的回归用例，再改最小代码；纯颜色/间距不写镜像实现测试，以布局可见性和截图判断。

每阶段新增 `docs/ui-review-evidence/stage-N/`（**拟新增目录**）：记录base commit、diff文件列表、运行命令/退出码/测试摘要、Qt/DPR/窗口尺寸、截图、未通过项。图片从build复制出来后才能运行会清build的打包脚本。不得覆盖用户已有证据。每项记录为通过/失败/未执行三者之一；缺硬件或人工证据不算通过。

共同止损：目标路由、查询/命令序列、原始文件/hash、单位/精度、旧配置或资源回收出现差异，立即暂停本阶段，保留最小复现；只回退本阶段自己的变更，不reset/清理用户已有工作。回滚点为修改前commit+阶段patch；是否提交由仓库工作流决定，不擅自合并/发布。

### 阶段0：建立可重现基线并封堵目标错位

- 目标：先解决P0，再冻结当前真实UI证据；ID：UI-01、UI-20的基线部分。
- 文件：`P/connection_view.py`、`P/main_window.py`、`app.py`；仅必要时`P/app_controller.py`只读通知；`tests/test_connection_widgets.py`、`tests/test_app_smoke.py`、`tools/capture_visual_baseline.py`、visual manifest。
- 前置：确认当前HEAD与本文差异；恢复本轮探针结论，不运行真串口/监听；保存旧PNG。
- [ ] 记录三Tab、CDC/Wi-Fi、空节点/双节点/离线节点快照，所有节点、状态和数据保持一致。
- [ ] 在连接widget测试构造B在线+A离线，先选B再点A，验证当前可视操作目标错位；app测试以两个fake transport检查实际START/STOP/WM/CLI归属。
- [ ] 实施UI-01最小方案：离线行不可作为操作选择；selected_node_changed回写列表与目标摘要；用QSignalBlocker阻断刷新引发的命令或重入。掉线自动替代目标必须有同一回传路径。
- [ ] 扩展截图工具，只新增测试参数，不改变产品启动和连接行为；输出页面、模式、状态、尺寸、DPR到manifest。
- [ ] 运行通用门禁，人工检查高亮、目标摘要、当前数据来源一致。
- 保护：节点业务选择/命令路由不重写；不增加协议命令。
- 自动/人工验收：A离线不能造成误导选择；B收到的每条命令与界面目标一致；最后节点离线控件不继续向旧目标发命令；旧CLI原文保留。
- 回滚/止损：若出现重复选择信号或无法明确控制器目标，不用猜测默认第一节点掩盖问题，暂停。
- 保存：A/B选择、A离线、B掉线三组截图和fake命令日志。阶段0未通过不得做大规模视觉修改。

### 阶段1：低风险主题与控件一致性

- 目标：输入控件和禁用/焦点外观可信；ID：UI-10、UI-11。
- 文件：`P/theme.py`、`P/controls.py`、`P/connection_view.py`、`P/main_window.py`；`tests/test_widgets.py`必要几何断言。
- 前置：阶段0通过；复用现有COLORS/SPACE。
- [ ] 将Wi-Fi网卡控件替换为IntegratedComboBox，保留itemData/currentIndexChanged接线。
- [ ] 补齐QSpinBox与输入族的minimum-height、padding及上下按钮区域；QSS增加focus/pressed、danger:disabled；card-actions透明。
- [ ] 给连接/START设primary展示角色，确认disabled不被role覆盖；不改任何setEnabled条件。
- [ ] 四种DPR渲染Wi-Fi表单、按钮六状态，检查命中/展开和Tab焦点。
- [ ] 通用门禁，比较端口默认值、范围和配置对象一致。
- 保护：协议、参数、控件信号触发次数、选项不变。
- 验收：下拉有箭头；两个端口框与邻近输入同高度且可增减；断开时STOP/DISCONNECT明显禁用；不因主题增宽造成新的按钮裁切。
- 止损/回滚：新主题使布局超出，先回退该选择器而非缩小全局字体。
- 保存：前后配对截图、控件尺寸和DPR表。

### 阶段2：核心状态闭环与小窗口布局

- 目标：把连接、采集、暂停、记录、断开、错误的作用范围说清楚；ID：UI-02/03/04/05/06/07/12/19。
- 文件：`app.py`、`P/main_window.py`、`P/app_controller.py`、`P/connection_view.py`、`P/orientation_view.py`、`P/diagnostics_view.py`、`P/vibration_view.py`；必要时拟新增`P/ui_state.py`；相应三组widget/app测试。
- 前置：阶段0/1通过。先列状态真值表，再实现；不得顺手改变AcquisitionController。
- [ ] 建立listener、selected target、reported firmware state、display pause、record result分别来源的只读映射；无节点操作禁用原因就近可见。监听关闭入口保持可达。
- [ ] 接入全局暂停展示；在暂停切节点、断开时清晰标明来源和末值，Diagnostics按None清来源组；复用现有0.5s规则。
- [ ] 增加录制只读结果通知，覆盖OSError/待UUID/部分失败；按钮意图与成功状态分开，路径只显示真实controller路径；不改armed/recorder生命周期。
- [ ] 增加非模态错误区、Console未读标记、报告状态和待确认状态；保留500ms grace和查询时序；程序回显WM/LIVE TARGET用QSignalBlocker；无响应不自动重发。
- [ ] 节点列表按ID更新，保留同节点dirty别名；空节点保存禁用并显示校验错误。
- [ ] Wi-Fi表单内容滚动化；按卡片可用宽度重排姿态/健康/曲线操作区；先保持当前最小窗口，后续阶段再降低限制。
- [ ] 以下状态逐一做fake接线测试：离线、仅监听、连接待UUID、IDLE、ACQUIRE、请求失败、暂停、录制失败、断开、重连、更换选中节点。
- [ ] 通用门禁及1080×700/1440×900截图检查，记录所有与旧结构断言的有意变化。
- 保护：默认、范围、输出精度、控制顺序、Pause业务合同、RECORD ALL合同、QSettings键和设备参数全部不动。
- 验收：无节点START/WM/CLI不可发；采集/记录继续而Pause明显；失败不呈“录制成功”；断开无LIVE；B无状态不显示A字段；小窗表单/8指标全部可达；草稿不被同节点刷新覆盖。
- 止损：若新的状态投影要求改变设备规则，暂停该项并保留原行为；不能为“禁用按钮正确”去发额外STATE查询。
- 保存：状态真值表、fake命令序列、录制失败路径、两尺寸两模式三页截图。

### 阶段3：实时图表、诊断和日志效率

- 目标：明确数据含义、便于查障且刷新可控；ID：UI-09/13/14/15/16/17/22/23。
- 文件：`P/vibration_view.py`、`P/diagnostics_view.py`、`P/console_view.py`、`P/main_window.py`、`P/orientation_view.py`、`P/app_controller.py`、`app.py`；新增性能测试仅针对UI任务，不改变现有parser基准；更新手册。
- 前置：阶段2状态正确；优先测试负载，不先重构store。
- [ ] 测量第7章基线；识别snapshot/渲染/文本哪部分占用时间。
- [ ] 若绘制是瓶颈，缓存最新快照、仅可见页绘制、只更新改变文本；回页刷新最新；不得跳过身份、CLI、导出终态或health处理。
- [ ] 曲线加RESET VIEW/FOLLOW说明；空数据/未知/暂停清楚区分；保留数组、时间轴和AUTO Y原语义。
- [ ] 健康未知值改展示—；非零加文本说明；姿态卡共享新鲜度和箭头说明；不新增阈值。
- [ ] Diagnostics加字段查找、分区定位和可复制长值；所有原字段仍在。
- [ ] Console加时间/节点来源、有界筛选/搜索、清显示/跟随开关；最小新增来源信号与app接线；命令文本不改，长响应完整复制，避免另一个无界缓存。
- [ ] 补导出只读指导/终态显示，未知总量不伪造百分比。
- [ ] 通用门禁、30分钟基准、交错A/B日志、EXPORT终态和文件一致性回归。
- 保护：采样/选点/数据完整性、协议响应、记录原文/格式/路径不变。
- 验收：按第7章性能预算；隐藏页回来显示最新；搜索/复制保原文，日志block≤2000且跟随关闭不抢位置；EXPORT_COMPLETE/EMPTY/ABORTED仍正确收尾；0.001g轴倍率可解释。
- 止损：瓶颈在store算法则独立记录接口最小适配，不能以UI任务更换包络/添加Kalman；如新日志容量策略会丢必要响应，保留原始处理路径并暂停策略变更。
- 保存：性能CSV/摘要、相同输入的输出hash对照、图表交互前后截图、节点来源日志。

### 阶段4：DPI、窗口适配与可访问性

- 目标：在真实工作区中可使用；ID：UI-08/18/24，复验UI-07/19。
- 文件：`P/main_window.py`、`P/orientation_view.py`、`P/connection_view.py`、`P/console_view.py`、`P/theme.py`、`P/splitter.py`、`app.py`；截图工具与UI测试。
- 前置：阶段2重排可用；先用无设备模拟窗口原生运行，不创建真实transport。
- [ ] 根据screen.availableGeometry约束首次显示，重排/滚动完成后下调硬最小尺寸；主操作不得出屏；不将DPR再次乘到Qt尺寸。
- [ ] 增RESET LAYOUT，若增加持久化仅用ui/*新键，检查离屏/损坏配置回落。
- [ ] Label buddy、accessibleName、Tab路径和焦点样式；替换Pause缺字形；不新增全局设备命令快捷键。
- [ ] 执行第8章全部主矩阵，175%补测及跨屏测试；字体放大、长字符串、OpenGL和fallback逐项记录。
- [ ] 通用门禁+配置兼容测试，更新通过的尺寸/DPI证据，不把未测格标绿。
- 保护：数据格式/单位、默认配置、控制语义、资源回收不变。
- 验收：1920×1080/200%含任务栏下STOP/连接/退出在屏内，所有字段可达；纯键盘核心任务可完成；多屏移动正常、布局重置可恢复；小于建议内容区使用滚动兜底。
- 止损：若最低支持环境无法满足，记录具体分辨率/控件并标未通过，请求产品确定支持范围，不能删除低分辨率验收项伪装通过。
- 保存：每矩阵截图与geometry/DPR，键盘操作记录、GL模式、字体回退与对比度结果。

### 阶段5：直接技术债收敛、发布验证和交接

- 目标：收口回归，只有证据支持时处理阻塞收尾；ID：UI-21、UI-20收口；复验全部ID。
- 文件：`P/app_controller.py`（必要适配）、`tests/test_app_smoke.py`、visual manifest、`docs/USER_MANUAL_zh-CN.md`、本计划验收状态；打包配置只验证，不无故修改。
- 前置：阶段0–4结果已确认，P0/P1未通过项逐一清单化。
- [ ] 用慢fake transport/writer验证停止记录/断开/退出UI时延；没有超预算就不重构生命周期。
- [ ] 如必须异步收尾，另列最小适配步骤、对象线程归属及原close/quit/wait/finalize顺序；先加超时/重复关闭回归，再实施；禁止terminate与提前丢引用。
- [ ] 汇总全部24项状态、截图和业务保护清单结果；更新手册入口/状态说明，保留硬件操作顺序。
- [ ] 运行通用门禁；把build中的证据复制出后，使用`powershell -ExecutionPolicy Bypass -File .\tools\package_host.ps1`构建。该脚本会重建build/host-package环境并可能联网安装依赖，不得使用SkipTests。
- [ ] 保存新EXE的manifest/SHA、包内smoke退出码，在无设备环境检查EXE三页；原生GL必须另验。
- [ ] 硬件验证仅在有明确设备操作授权后，依据第10章保护项执行；记录最终设备状态，不擅自恢复UART或发STOP。没有授权/设备，报告“硬件未验”，不能写最终实机通过。
- 验收：源/打包门禁通过；退出无存活worker或文件句柄，元数据完整；P0清零、P1无未解释失败；DPI/GL/硬件未执行部分明确列发布限制。
- 止损/回滚：不为打包通过改依赖主版本或协议；资源语义差异回退独立收尾适配。只回退自己阶段变更。
- 保存：最终报告、完整问题状态、发布包验证、剩余限制和可复现步骤。

## 12. Qoder 执行指令

1. 先完整阅读本文、当前源文件和README；目录缩写按第0章展开。确认当前HEAD及用户未提交修改，禁止覆盖用户工作。
2. 一次只执行一个阶段；首阶段执行0，不先做美化。每阶段完成后向用户报告并等待确认再继续。
3. 修改前保存可运行基线、对应页面截图和命令/文件输出合同；不要拿旧PNG当当前实现。
4. 优先复用Qt布局、SPACE/COLORS/IntegratedComboBox；不要换框架、添加主题库、大拆AppController或重写数据层。
5. 第10章为强保护边界；UI-21或UI-09需要最小接口适配时单列差异与回归，不默认获得底层行为修改授权。
6. 所有程序设置combo/check状态使用适当信号阻塞；必须证明不会发额外设备命令。界面高亮/数据/命令目标始终一致。
7. 代码与计划不一致时，暂停受影响项并记录：ID、计划符号/事实、当前证据、行为影响、可选处理。不要猜测不存在的接口或从历史设计移植未实现功能；不受影响的只读检查可继续。
8. 所有【推测】先复现/测量，不能当确定缺陷重构；无法验证的项目标【待确认】，写明阻塞哪项验收。
9. 每阶段做通用门禁、对应行为测试、人工截图/键盘验收；自动测试绿不替代DPI/原生GL。先修阶段回归再进入下一阶段。
10. 不删除“不好改”的页面/字段/CLI入口/右键菜单；不新增自动START/STOP、重试、目标切换、导出流程。危险操作确认若会改变既有操作序列，另行决策。
11. 不连接真实设备、不运行硬件acceptance脚本、不执行固件构建/烧录或修改邻接STM32/ESP32仓库，除非另获明确授权。历史文档的固件Stage1要求不直接套到本独立仓库。
12. 每阶段交付：问题ID状态、修改摘要、文件清单、测试结果/退出码、截图清单、保护项回归、差异与遗留项、下一阶段风险。未完成验收不使用“全部通过”。

## 13. 最终验收清单

- [ ] 三主Tab、Wi-Fi配置、节点管理、曲线、姿态、八项数值、八项健康、诊断、Console入口完整。
- [ ] 高亮节点、显示数据来源、START/STOP/WM/CLI命令目标一致；离线节点不能造成误操作。
- [ ] 连接、监听、等待节点、设备IDLE/ACQUIRE、暂停、重连、断开、错误明确区分。
- [ ] loading/pending、empty、error、disabled和unknown展示完整，命令请求不冒充设备确认。
- [ ] 无设备CONNECT不可误点；仅监听时节点命令不可用；停止监听/STOP/断开正确可达。
- [ ] Pause明确只冻结显示；采集和记录继续；恢复到最新快照；切节点/断开无旧LIVE误导。
- [ ] RECORD ALL范围清楚，UUID等待、部分失败、写盘失败与真实结果一致，保存路径真实。
- [ ] 标签/单位/参数范围/默认值/数值精度保持；WM/目标报告值回显不发送命令。
- [ ] 主要/次要/危险/禁用按钮层级清楚，焦点和pressed可辨，无缺字形图标。
- [ ] 1080×700表单无挤压；小工作区滚动能到全部字段；窗口/分隔器重置可恢复。
- [ ] 曲线空数据/缩放/平移/恢复/XYZ/AUTO Y可用；g与自动前缀解释正确。
- [ ] 数据展示30分钟基准有证据，5000点/2000blocks保持，无未解释持续增长或交互停顿。
- [ ] Console时间/来源/搜索/复制/跟随行为正确，响应原文未变；未选节点不被错认为当前回复。
- [ ] Diagnostics字段完整、可复制、长错误可读，切节点不残留，reserved 0仍有说明。
- [ ] Windows 100%、125%、150%、200%矩阵通过，175%抽测记录；最小/默认/最大化可用。
- [ ] 多显示器DPI切换、移除显示器、字体放大、高对比度、读屏和键盘路径完成验证。
- [ ] OpenGL与fallback独立通过，方向/加速度计算和相机操作不变。
- [ ] 协议golden、命令字节/顺序、文件格式/hash、metadata、配置兼容性、节点重连与记录分段通过。
- [ ] 线程、计时器、监听、录制器退出收尾与基线一致，无强制终止或资源泄漏。
- [ ] 没有计划外协议/算法/默认参数/保存格式/固件更改。
- [ ] 源测试、compile、smoke、diff检查及发布包验证通过；硬件未测时明确标未测。
- [ ] 所有24项最终状态、文档/截图/遗留差异已保存；未确认项没有伪装为完成。

## 14. 待确认问题

以下不阻止Qoder启动阶段0；能从代码确定的默认值/页面数量不再询问用户。

| 待确认项 | 影响的决策 | 验证责任/方式 |
|---|---|---|
| 最低现场分辨率/工作区，是否必须支持1366×768的200% | UI-08窄屏回退方式和发布支持范围；本计划默认尽量可达、不直接剔除 | 产品/现场确认，原生矩阵截图 |
| 是否保留英文UI，是否全面中文化 | 文案长度、字体与按钮宽度；当前只保留英文并补解释 | 用户/产品选择；不影响P0修复 |
| IIS数据“过期”的时间阈值与现场容忍度 | UI-17若增加IIS freshness提示；不能用JY的0.5s直接代替 | 产品/采集负责人；先显示已知连接/暂停状态 |
| 目标机器OpenGL/驱动与多屏配置 | UI-08/22真实渲染、上下文切换、回退提示 | 在目标Windows机器无设备模拟验证 |
| 实际16节点负载、磁盘条件与延迟目标 | UI-09/21性能结论，是否需要最小接口适配 | 固定环境模拟测量；实机需授权 |
| 硬件联锁/导出期间命令可用性细节 | 是否可以进一步按状态禁用具体命令；本轮只禁无目标，不擅自替代设备规则 | 设备协议负责人/授权硬件验证 |

## 15. 建议暂缓或不做的事项

- 不做Kalman/滤波、FFT、算法更换、重采样或新历史回放页：历史文档并非已实现事实，本轮明确保护采集与解析规则。
- 不换PyQt框架，不引入完整MVVM框架或庞大设计系统；已有主题/spacing/Widgets足以处理多数项。仅在多处UI状态重复时新增小型只读投影。
- 不自动执行“STOP→切通道→START”，不自动重连后启动设备，不自动重试CLI；UI应解释原有操作顺序。
- 不新增危险AT命令面板或全局快捷START；原始Console功能保留，风险操作的重新设计另立项。
- 不立即优化原始sample_store/包络算法或关闭写盘校验；先以UI-09测量证明瓶颈，再评估最小只读接口。
- 不把全部日志永久写入新格式，不扩为每节点无界缓存；先做有限展示与查找。新UI日志导出需独立定义用途。
- 不因审美偏好删除节点区、诊断字段、模式提示或分隔器；优先折叠/重排/辅助说明。
- 不强制STOP二次确认、不改关闭窗口自动行为；这些可能拖慢安全操作或改资源生命周期，应另评估。
- 不把历史README中的COM6、旧硬件验收记录当作当前硬件事实，不执行旁边STM32/ESP32工程的编译或烧录。
- 不把离屏DPR通过、172测试通过或旧发布包存在当作全部UI/硬件验收通过；缺失证据保持待确认。
