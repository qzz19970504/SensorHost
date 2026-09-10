# SensorHost 上位机操作指南设计

## 目标

制作一份面向第一次使用者的简洁中文 Word 操作指南，让读者能够看懂界面分区，并完成设备连接、实时波形查看、数据记录、SD 卡历史数据导出和本地回放。

## 读者与范围

- 读者：需要使用 SensorHost 上位机查看 STM32F407 传感器数据的现场操作人员。
- 输出：`docs/SensorHost上位机操作指南.docx`，页数以内容完整和图片清晰为准，不设固定页数上限。
- 语气：短句、按按钮和界面区域说明，不展开协议、源码和完整故障诊断。
- 范围：CDC 连接为主，补充 WI-FI 入口说明；覆盖 LIVE MONITOR、DIAGNOSTICS、CONSOLE、DEVICE SD RECORDS 和 LOCAL EXPORT LIBRARY 的基础用途。
- 明确边界：当前上位机支持从设备 SD 卡导出到电脑并回放，不提供将本地文件上传回 SD 卡的界面入口。

## 文档结构

1. 首页：标题、适用范围、最短上手路径。
2. 界面总览：顶部连接区、采集工具栏、设备列表、三个主要页面的职责。
3. 连接设备：插入 USB、REFRESH、选择 CDC/COM 口、CONNECT、选择 LIVE TARGET=CDC、START；说明 CONNECT 只建立连接，不自动开始采集。
4. 查看波形：进入 LIVE MONITOR，说明 X/Y/Z 三轴曲线、时间窗、AUTO Y、RESET VIEW、姿态卡片、PAUSE 和 Stream Health 的基础判断。
5. 记录实时数据：RECORD 的开始/结束，说明它与 SD 导出不同，并给出默认保存位置。
6. SD 卡导出和下载：STOP 后进入 SD ARCHIVE，REFRESH、选中设备、EXPORT SELECTED、查看进度，并配 SD 页面和进度截图。
7. 导入导出文件并回放：从 LOCAL EXPORT LIBRARY 选择 complete 文件，OPEN FOR PLAYBACK 或双击，说明播放条操作，并配本地回放截图和数据流向图；明确这里的导入是上位机打开本地文件，不是上传回 SD 卡。
8. 停止与常见提示：RECORD → STOP → DISCONNECT；提供“已连接但无波形”和“选择 CDC 报 ERROR:STATE”的简短处理。

## 图片计划

- 使用已有真实界面截图，不使用未经验证的仿制界面。
- 图 1：`docs/ui-review-evidence/stage-4/native-live-1440x900-scale1.5.png`，标注顶部连接区、采集工具栏、设备列表、波形区和姿态区。
- 图 2：`docs/ui-review-evidence/stage-5/native-cdc-live.png`，用于说明 CDC 已连接、LIVE TARGET、START、三轴波形和 Stream Health。
- 图 3：`docs/ui-review-evidence/stage-5/native-cdc-diagnostics.png`，说明 DIAGNOSTICS 用于看帧数、CRC 和设备状态。
- 图 4：`docs/ui-review-evidence/stage-5/native-cdc-console.png`，说明 CONSOLE 用于看命令回复及 SD 导出状态。
- 图 5：`docs/artifacts/sensorhost_sd_archive_overview.png`，说明 SD ARCHIVE 页面中的设备存档、本地导出库和操作按钮。
- 图 6：`docs/artifacts/sensorhost_sd_export_progress.png`，说明 EXPORT PROGRESS 和 CANCEL。
- 图 7：`docs/artifacts/sensorhost_playback_controls.png`，说明本地导出文件打开后的回放控制条。
- SD 卡部分：制作一张低复杂度的黑白/青色流程图，表达“设备 SD 卡 → EXPORT SELECTED → 电脑本地导出文件 → OPEN FOR PLAYBACK”，并在旁边注明不支持反向上传。

## 版式

- A4 纵向，正文 10.5–11 磅，使用清晰的中文无衬线字体。
- 黑色标题与章节标题，使用青绿色作为少量强调色；不使用大面积装饰和复杂卡片。
- 图片采用行内方式并配独立图注；图片不过度缩放，保证按钮文字可辨认。
- 使用短表格列出功能区与用途，使用编号步骤列出操作路径。
- 页脚显示“SensorHost 上位机操作指南”和页码；不加入作者、版本承诺或未经验证的设备信息。

## 验收标准

- Word 能正常打开，标题和章节层级清楚。
- 连接、波形、RECORD、SD 导出/回放的步骤与现有程序和 `docs/USER_MANUAL_zh-CN.md` 一致。
- 明确 STOP 是导出前置条件，导出成功会清空设备 SD 环形存档，且当前没有“上传回 SD”入口。
- DOCX 经 `render_docx.py` 渲染为逐页 PNG 后逐页检查，无图片越界、文字遮挡、表格截断或页脚错位。
