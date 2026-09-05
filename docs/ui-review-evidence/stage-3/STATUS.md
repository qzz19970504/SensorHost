# Stage 3 — 图表/诊断/日志效率（UI-09、13、14、15、16、17、22、23，8/8）

- 提交：`0996aeb`(17)、`f7615b4`(13)、`e52d0f6`(16/14)、`047aae2`(22)、
  `bae48b0`(15)、`5c4c0b6`(09)。
- 门禁：pytest 至 200 passed；compileall 0；smoke 0；diff --check 0。
- 回归测试：未知计数 `—`、诊断换行可选中、Console 时间戳/FOLLOW/清屏/来源、
  RESET VIEW、隐藏页延迟渲染等。
- 截图：`native-live-1440x900.png`（原生，含 OPENGL 3D 姿态与 RESET VIEW）。
- 性能：`tools/ui_perf_benchmark.py`（§7.3 测量工具）短跑实测
  p50=0.600ms / p95=1.135ms / max=1.554ms → 单节点 p95 ≤ 33ms 预算 PASS；
  30 分钟完整验收可 `--minutes 30` 运行（提交 `90ea057`）。
- UI-09 实施隐藏页延迟渲染+跳过不变文本，未做投机性底层改动。
