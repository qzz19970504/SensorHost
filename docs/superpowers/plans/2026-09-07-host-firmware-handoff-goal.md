# 上位机固件接口交接文档 Goal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 创建一份可直接交给 Codex 以 Goal 形式执行的中文提示词，用静态取证生成精简的单一上位机固件接口交接手册。

**Architecture:** 提示词将三个独立仓库声明为有优先级的事实源，限制 Codex 只做静态分析，并规定单文档结构、冲突处理、来源追踪和验收标准。生成阶段只新增提示词文件，不修改任何实现代码。

**Tech Stack:** Markdown、PowerShell、Git、ripgrep

---

### Task 1: 生成并验证 Goal 提示词

**Files:**
- Create: `D:\Codes\SensorHost\上位机固件接口交接文档生成任务.md`
- Reference: `D:\Codes\SensorHost\docs\superpowers\specs\2026-09-07-host-firmware-handoff-goal-design.md`

- [x] **Step 1: 编写 Goal 提示词**

提示词必须完整写明：角色和目标、三个仓库的绝对路径与职责、事实来源优先级、只做静态分析的限制、唯一输出文件、目标读者、必需章节、内容取舍、工作步骤、冲突和待确认项处理、质量门禁及完成条件。

唯一产物路径固定为：

```text
D:\Codes\SensorHost\docs\上位机固件接口交接手册.md
```

必需内容固定为：系统与职责边界、连接和默认参数、CDC 与 Wi-Fi/TCP 接入、SDF1 解析、传感器换算、AT 命令与状态、超时重试、诊断恢复、实时流与 SD/EXPORT 差异、已知限制、最小实现和联调清单、事实来源索引。

- [x] **Step 2: 检查提示词结构与禁用项**

运行：

```powershell
rg -n "角色|目标|事实源|静态分析|上位机固件接口交接手册|SDF1|AT 命令|CDC|Wi-Fi|待实机确认|验收" '.\上位机固件接口交接文档生成任务.md'
rg -n "连接硬件|烧录固件|修改实现代码|评价.*UI" '.\上位机固件接口交接文档生成任务.md'
```

预期：第一条命令命中所有关键约束；第二条命令只命中明确的禁止性表述，不出现要求执行这些动作的指令。

- [x] **Step 3: 检查占位符、格式和工作区状态**

运行：

```powershell
rg -n "TBD|TODO|待补充|这里填写|<[^>]+>" '.\上位机固件接口交接文档生成任务.md'
git diff --check
git status --short
```

预期：占位符扫描无输出；`git diff --check` 成功；工作区只出现计划内新增文档。

- [x] **Step 4: 提交提示词**

运行：

```powershell
git add -- '.\上位机固件接口交接文档生成任务.md' '.\docs\superpowers\plans\2026-09-07-host-firmware-handoff-goal.md'
git commit -m "docs: add host firmware handoff goal prompt"
```

预期：Git 创建一个仅包含 Goal 提示词和本计划的文档提交。
