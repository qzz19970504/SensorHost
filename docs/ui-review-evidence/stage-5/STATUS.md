# Stage 5 — 技术债收敛、发布验证与交接（UI-21、发布包、手册）

- 提交：`3c4e754`(UI-21 测量)、`d711c94`(UI-20 工具)、`c66aafc`(手册)。
- 源门禁：pytest 200 passed；compileall 0；smoke 0；diff --check 0。
- 发布包：`tools/package_host.ps1`（未用 SkipTests）→
  `dist/host/STM32SensorHost-0.1.0-win64.exe`（64,517,198 B），
  manifest `dist/host/STM32SensorHost-0.1.0-win64.json`
  sha256 `adc1d480278b644bdc8af5386a458da09bb679afd928eada711803196e626c57`；
  build-venv 内 pytest 200 passed、打包 `--smoke-test` 通过。
- UI-21：慢传输断开时延在 3s 线程停止预算内 → 按计划不重构生命周期。
- 手册：`docs/USER_MANUAL_zh-CN.md` 已更新新 UI 状态/控件，硬件操作顺序未改。
- 硬件（CDC，COM6 VID_0483/PID_5740）：`tools/cdc_acceptance.py` 实机运行
  （`acceptance.json` WM256、`acceptance-wm511.json` WM511）：连接、IDLE→
  LIVESTREAM=CDC→START 握手全 true、CRC 0、记录字节=接收字节、回放帧数一致、
  结束恢复 IDLE+LIVESTREAM=UART 成功。但固件 `source_drops` 增量非零
  （WM256: 2477、WM511: 1307）且 WM256 有 sequence_gaps 609（WM511 降至 11）
  → 验收 `passed=False`，属设备/固件侧 IIS 源丢弃，与上位机 UI 无关。
- 实机 UI 验证：`native-cdc-live.png`（原生 windows，真实 CDC 数据）确认目标摘要、
  节点高亮、无节点门控、未知计数 `—`、Console 未读标记、原生 OpenGL 均正确。
- 实机 RECORD 验证：点击 RECORD 按钮后按钮显示 `● RECORD · 1`，并写出
  `segment-001.sdf1`（647,804 B），停止后文件完整；UI 记录链路实机端到端可用。
- Wi-Fi：当前环境无法测试（无热点/ESP），未验。
- 仍待原生环境：OS 显示缩放切换/多屏/读屏/高对比度；16 节点负载。
