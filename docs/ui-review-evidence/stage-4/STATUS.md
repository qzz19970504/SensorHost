# Stage 4 — DPI/窗口适配与可访问性（UI-08、18、24）

- 提交：`44a80e5`(08)、`0abb084`(18)、`f7615b4`(24)。
- 门禁：pytest 至 200 passed；compileall 0；smoke 0；diff --check 0。
- 回归测试：最小尺寸+clamp、label buddy/accessibleName、RESET LAYOUT。
- 原生渲染证据：`native-live-1440x900.png`、`native-live-1440x900-scale1.5.png`
  （windows 平台 + QT_SCALE_FACTOR 1.5）。
- offscreen DPR 矩阵：`dpr-live-1920x1080-scale{1,1.25,1.5,2}.png`（build/ui-review）。
- 未验证：真实 OS 显示缩放切换、多屏热插拔、读屏/高对比度（需原生交互/辅助技术）。
