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
- 未验证：硬件实机验收（无设备/授权，按计划报告"硬件未验"）。
