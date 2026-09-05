# 上位机单文件构建环境

本文档用于在 Windows 上重复构建、验证和交接 STM32 Sensor Host。构建产物是 Windows 10/11 x64 的单文件、无控制台 PyQt 应用；当前不做代码签名，因此首次运行可能出现 SmartScreen 或杀毒软件提示。

## 一条命令完成构建

在仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\package_host.ps1
```

脚本会按顺序创建隔离环境、安装依赖、运行上位机与协议测试、构建单文件 EXE、执行无串口的启动自检，并生成 SHA-256 manifest。成功输出位于：

```text
dist/host/STM32SensorHost-0.1.0-win64.exe
dist/host/STM32SensorHost-0.1.0-win64.json
```

版本号来自 `host/pyproject.toml` 安装后的包元数据。升级版本后文件名会自动变化，不需要修改脚本。

## Python 解析顺序

脚本按以下顺序选择 Python 3.11+：

1. 命令行显式指定的 `-Python`。
2. Codex 缓存运行时 `C:\Users\44575\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`。
3. Windows Python Launcher 的 `py -3.12`。
4. `PATH` 中的 `python.exe`。

需要指定其他可执行文件时运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\package_host.ps1 `
  -Python 'C:\path\to\python.exe'
```

所有 Python 包安装到 `build/host-package/.venv/`。脚本每次只重建这个仓库内的专用构建目录，不修改系统 Python、固件工具链或开发环境。依赖 wheel 下载后会进入 pip 的用户缓存，后续构建可复用。

## 固定的构建输入

- 运行依赖与应用版本：`host/pyproject.toml`。
- 构建依赖：`host/requirements-build.txt`，当前固定 `pyinstaller==6.16.0`。
- 打包规则：`host/STM32SensorHost.spec`。
- 构建入口：`tools/package_host.ps1`。

PyInstaller spec 显式收集 pyqtgraph 和 PyOpenGL，Qt 插件由 PyInstaller 的 PyQt6 hook 收集。`EXE` 直接包含 Python 归档、动态库与资源，且没有 `COLLECT` 阶段，因此输出是单文件；`console=False` 确保正常启动不出现控制台窗口。

## 自动验证内容

默认构建不可跳过以下门禁：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest .\host\tests .\test\test_protocol.py -q
```

打包后脚本运行：

```powershell
.\dist\host\STM32SensorHost-0.1.0-win64.exe --smoke-test
```

这个模式会加载字体和主题、构造完整主窗口及 2D OpenGL 降级视图、处理一轮 Qt 事件后退出；它不会枚举或打开串口。30 秒内未退出或退出码非零都视为构建失败。

`-SkipTests` 只适合已经在同一提交上完成全量测试后的本地重复打包：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\package_host.ps1 -SkipTests
```

正式交接构件不得使用 `-SkipTests` 作为唯一证据。

## 校验构件完整性

查看 Windows 计算的哈希：

```powershell
Get-FileHash .\dist\host\STM32SensorHost-0.1.0-win64.exe -Algorithm SHA256
Get-Content .\dist\host\STM32SensorHost-0.1.0-win64.json
```

`Get-FileHash` 的 `Hash` 应与 JSON 的 `sha256` 完全一致，JSON 的 `bytes` 应等于 EXE 文件大小。交接时应同时传递 EXE 和 JSON。

## 升级和复现步骤

1. 需要发布新应用版本时，先修改 `host/pyproject.toml` 的 `version`，同步发布说明并运行完整 Python 测试。
2. 需要升级 PyInstaller 时，只修改 `host/requirements-build.txt` 的精确版本，不使用无上限范围。
3. 运行不带 `-SkipTests` 的完整打包命令。
4. 检查 `build/host-package/pyinstaller-work/STM32SensorHost/warn-STM32SensorHost.txt`，确认没有遗漏本项目实际使用的模块。
5. 运行 `powershell -ExecutionPolicy Bypass -File .\tools\test_stage1.ps1`，确保上位机交付没有掩盖固件回归。
6. 核对 EXE/JSON 哈希，并在一台未安装 Python 的 Windows x64 机器上启动 GUI。

构建目录和 `dist/host/` 均被 Git 忽略。不要提交 EXE、临时 venv 或 PyInstaller 中间文件；源代码、spec、固定依赖和本说明才是可复现输入。

## 常见问题

### 首次启动较慢

单文件 PyInstaller 应用会先解压到用户临时目录，冷启动通常比源码或单目录构建慢。`--smoke-test` 的 30 秒门限包含这一过程。

### 杀毒软件或 SmartScreen 告警

当前 EXE 未签名，PyInstaller 单文件也可能触发启发式误报。应先通过 JSON 核对 SHA-256，并从受信任的内部渠道传递；对外发布前应增加组织代码签名，不要要求用户全局关闭杀毒软件。

### Qt platform plugin 无法加载

删除 `build/host-package/` 后重新执行完整脚本，检查 PyInstaller warning 文件，并确认使用的是 64 位 Python。不要把系统 PyQt6 与构建 venv 混用。

### 缺少运行库或程序立即退出

先直接运行 `--smoke-test` 并检查退出码。若目标机缺少 Microsoft Visual C++ Runtime，应安装 Microsoft 官方 x64 Redistributable；不要从不明网站复制 DLL 到 EXE 同目录。

### 3D 视图不可用

缺少兼容 OpenGL 驱动时程序自动显示 `2D FALLBACK`，三轴波形、姿态数值、采集、诊断和录制仍可使用。更新显卡驱动后再验证 3D 视图。

### 找不到缓存 Python

使用 `-Python` 指定一套 64 位 Python 3.11 或更新版本。脚本会在该解释器旁创建独立 venv，不要求把 Python 永久加入 `PATH`。
