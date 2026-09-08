# UI 审查执行最终报告（UI_REVIEW_PLAN.md）

- 分支：`ui-review-plan`（基线 `398128e`）；提交数：34；工作树干净。
- 源门禁：pytest **205 passed**；compileall 0；`--smoke-test` 0；`git diff --check` 0。
- 发布包：`dist/host/STM32SensorHost-0.1.0-win64.exe`（最终代码重建，64,520,814 B，
  sha256 `c575b70f31f8ba17fba2eea03c48ab4cd2cec5b693ef33013c4f7b6b7b37fd35`），
  build-venv 门禁与打包 `--smoke-test` 通过。
- 性能（§7.3）：30 分钟单节点 GUI 回调 count=38388、p50=0.655ms、p95=1.486ms、
  max=5.997ms → p95 ≤ 33ms **PASS**（`stage-3/ui-perf-30min.csv`）。

## 24 项状态

| ID | 阶段 | 代码 | 验证 | 备注 |
|---|---|---|---|---|
| UI-01 | 0 | ✅ | fake-transport 路由测试 + 实机 | P0 高亮≠目标已封堵 |
| UI-02 | 2 | ✅ | 测试 + 实机截图 | 无节点门控 |
| UI-03 | 2 | ✅ | 测试 + 实机 | 暂停展示接线 |
| UI-04 | 2 | ✅ | 测试 + 实机 | 断开/切节点新鲜度 |
| UI-05 | 2 | ✅ | 测试 + 实机 RECORD | 录制数反馈/失败走横幅 |
| UI-06 | 2 | ✅ | 测试 + 实机 | 错误横幅+Console 未读 |
| UI-07 | 2 | ✅ | 测试 + 原生 1080×700 | 表单滚动+标签换行 |
| UI-08 | 4 | ✅ | 测试 + 原生/scale | clamp+降最小；OS 缩放切换未验 |
| UI-09 | 3 | ✅ | 30min 基准 PASS | 隐藏页延迟渲染；16 节点未验 |
| UI-10 | 1 | ✅ | 测试 + 原生 | combo 箭头/spinbox 输入族 |
| UI-11 | 1 | ✅ | 测试 + 原生 | disabled/primary/focus/pressed |
| UI-12 | 2 | ✅ | 测试 | 别名草稿/保存门控 |
| UI-13 | 3 | ✅ | 测试 + 实机 | 换行/可选中/搜索/分区/错误摘要 |
| UI-14 | 3 | ✅ | 测试 + 实机 | 时间戳/搜索/FOLLOW/清屏 |
| UI-15 | 3 | ✅ | 测试 | ALL NODES 来源归属 |
| UI-16 | 3 | ✅ | 测试 + 实机 | RESET VIEW |
| UI-17 | 3 | ✅ | 测试 + 实机 | 未知显 `—` |
| UI-18 | 4 | ✅ | 键盘测试 + accessibleName + 稳定Tab序 | 读屏/高对比度原生交互未验 |
| UI-19 | 2 | ✅ | 测试 + 原生 | 按卡宽重排 |
| UI-20 | 0/5 | ✅ | 工具+证据归档 | 截图工具参数化 |
| UI-21 | 5 | ✅ | 慢传输测量在预算内 | 不重构生命周期 |
| UI-22 | 3 | ✅ | 测试 + 原生 | 轴前缀/姿态语义说明 |
| UI-23 | 3 | ✅ | 测试 | EXPORT HELP 折叠指引 |
| UI-24 | 4 | ✅ | 测试 | RESET LAYOUT + ui/* 布局持久化（校验+clamp+reset清除） |

## 业务保护清单（第 10 章）结果

全部**未破**：协议帧/CRC/序列、CLI 命令字/顺序/CRLF、单位与精度、记录格式与路径、
QSettings 旧键（aliases/*、wifi/*）、节点身份路由、采集与展示分离、无自动
START/STOP/重试/目标切换、告警阈值未新增。回归：203 测试含协议 golden 与命令字节断言。

## 硬件（CDC COM6）

- 握手（IDLE→LIVESTREAM=CDC→START）、CRC 0、记录=接收、回放一致、恢复 UART：✅。
- 验收 `passed=False`：固件 `source_drops` 增量非零（WM256 2477 / WM511 1307）、
  WM256 sequence_gaps 609（WM511 11）→ 设备/固件侧 IIS 源丢弃，与上位机 UI 无关。
- 实机 UI：live/diagnostics/console/record 原生截图均正确（`stage-5/`）。

## 未验证（环境受限，非伪装完成）

1. Wi-Fi 硬件（无热点/ESP）。
2. OS 显示缩放切换 / 多屏热插拔 / 读屏 / 高对比度（需系统/辅助技术环境）。
3. 16 节点高负载合成基准。
4. 固件 source_drops 根因（超 UI 范围，需固件仓库/授权）。

## 待产品确认（§14，未阻塞执行）

最低现场分辨率支持范围；UI 语言全面中文化与否；IIS 过期阈值；目标机 OpenGL/多屏；
16 节点负载目标；硬件联锁细节。
