# Stage 3 — 图表/诊断/日志效率（UI-09、13、14、15、16、17、22、23，8/8）

- 提交：`0996aeb`(17)、`f7615b4`(13)、`e52d0f6`(16/14)、`047aae2`(22)、
  `bae48b0`(15)、`5c4c0b6`(09)。
- 门禁：pytest 至 200 passed；compileall 0；smoke 0；diff --check 0。
- 回归测试：未知计数 `—`、诊断换行可选中、Console 时间戳/FOLLOW/清屏/来源、
  RESET VIEW、隐藏页延迟渲染等。
- 截图：`native-live-1440x900.png`（原生，含 OPENGL 3D 姿态与 RESET VIEW）。
- 性能：`tools/ui_perf_benchmark.py`（§7.3 测量工具）。**30 分钟完整验收**
  （`ui-perf-30min.csv`）：count=38388、p50=0.655ms、p95=1.486ms、max=5.997ms
  → 单节点 GUI 回调 p95 ≤ 33ms 预算 **PASS**，且 max < 500ms 交互停顿阈值；
  RSS 未测（环境无 psutil）。16 节点负载未测（需多会话采集/记录合成，已注明）。
- UI-09 实施隐藏页延迟渲染+跳过不变文本，未做投机性底层改动。
