# Stage 0 — 基线与 P0 目标对齐（UI-01、UI-20）

- 基线提交：`398128e`（main）；分支：`ui-review-plan`。
- 提交：`4e3130a`（计划文档）、`ec1fcc0`（UI-01 修复）。
- 门禁（阶段收尾）：pytest 175 passed；compileall 0；smoke 0；`git diff --check` 0。
- 回归测试：`test_offline_node_cannot_become_command_target`、
  `test_set_selected_node_writes_back_target_without_reemitting`、
  `test_offline_node_does_not_steal_commands_end_to_end`（双 fake transport 路由）。
- 截图：修复后渲染见 `../stage-1/`、`../stage-2/`；审查期基线图在
  `build/ui-review/`（gitignored，含 48 图 CDC/WI-FI × 尺寸 × 页 × DPR 矩阵）。
- 未验证：实机误发（无设备）；UI-01 以 fake-transport 命令路由测试证明。
