# Stage 2 — 核心状态闭环与小窗布局（UI-02~07、12、19，8/8）

- 提交：`7872ce5`(03/04)、`c7628fa`(02)、`057647c`(06)、`abd517c`(07)、
  `8ef4327`(12)、`cc8ad8d`(05)、`bae48b0`(15/19 中之 19)、`b3d6df7`(07 窄面板修正)。
- 门禁：pytest 至 200 passed；compileall 0；smoke 0；diff --check 0。
- 回归测试：暂停/断开新鲜度、无节点门控、错误横幅+未读、滚动、别名草稿、
  录制数、按卡宽重排等（tests/test_widgets.py、test_connection_widgets.py、
  test_app_smoke.py）。
- 截图：`stage2-wifi-listening-1080x700.png`（offscreen）、
  `native-wifi-listening-1080x700.png`（原生 windows 平台，标签换行、仅垂直滚动）。
- 未验证：1080p@200% 真实工作区（需原生 OS 缩放切换）。
