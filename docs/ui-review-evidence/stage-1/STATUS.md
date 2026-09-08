# Stage 1 — 主题与控件一致性（UI-10、UI-11）

- 提交：`7a66737`。
- 门禁：pytest 179 passed；compileall 0；smoke 0；diff --check 0。
- 回归测试：`test_wifi_interface_combo_uses_integrated_chevron`、
  `test_wifi_spinbox_matches_line_edit_input_height`、
  `test_primary_and_danger_roles_mark_operation_hierarchy`、
  `test_theme_separates_disabled_danger_and_primary_roles`。
- 截图：`stage1-wifi-form.png`（offscreen，确认 combo chevron 可见、spinbox 不再偏矮）。
- 已知残留：spinbox 与 line edit 有 3px 原生按钮框高度差（不再偏矮）；像素级相等
  与箭头原生渲染见 `../stage-4/` 原生截图。
