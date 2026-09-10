# SensorHost 上位机操作指南 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create and visually verify a concise Chinese DOCX operator guide for SensorHost using verified UI screenshots and beginner-oriented steps.

**Architecture:** Build one self-contained DOCX from `python-docx`, using existing project screenshots, three generated-but-real Qt UI captures for SD export/playback, and one locally generated SD export flow diagram. Keep source content in the builder script so revisions are deterministic, then render the DOCX to PNGs and inspect every page.

**Tech Stack:** Bundled Python runtime, `python-docx`, Pillow, existing PNG screenshots, packaged `render_docx.py` and LibreOffice renderer.

---

### Task 1: Prepare verified content and design assets

**Files:**
- Read: `docs/USER_MANUAL_zh-CN.md`
- Read: `docs/ui-review-evidence/stage-4/native-live-1440x900-scale1.5.png`
- Read: `docs/ui-review-evidence/stage-5/native-cdc-live.png`
- Read: `docs/ui-review-evidence/stage-5/native-cdc-diagnostics.png`
- Read: `docs/ui-review-evidence/stage-5/native-cdc-console.png`
- Create: `docs/artifacts/sensorhost_sd_export_flow.png`
- Create: `docs/artifacts/sensorhost_sd_archive_overview.png`
- Create: `docs/artifacts/sensorhost_sd_export_progress.png`
- Create: `docs/artifacts/sensorhost_playback_controls.png`

- [ ] **Step 1: Create the SD flow image**

  Draw a compact 1600×420 PNG with four labeled stages in Chinese: `设备 SD 卡`, `EXPORT SELECTED`, `电脑本地导出文件`, and `OPEN FOR PLAYBACK`. Connect them left-to-right with arrows, and add a small bottom note: `当前版本不支持电脑文件上传回 SD 卡`.

- [ ] **Step 2: Capture the SD UI states**

  Run `tools/capture_sensorhost_archive_guide_screenshots.py` with the repository `.venv`, `QT_QPA_PLATFORM=offscreen`, and `PYTHONPATH=src`. Confirm the three PNGs show the SD archive list, an in-progress export with CANCEL, and the live monitor playback bar.

- [ ] **Step 3: Check the source facts**

  Confirm the guide states `STOP` before export, `CONNECT` does not start acquisition, `LIVE TARGET=CDC` is needed for USB live data, and `RECORD` is separate from SD export.

- [ ] **Step 4: Commit the design assets**

  ```powershell
  git add docs/artifacts/sensorhost_sd_export_flow.png docs/artifacts/sensorhost_sd_archive_overview.png docs/artifacts/sensorhost_sd_export_progress.png docs/artifacts/sensorhost_playback_controls.png
  git commit -m "docs: add SensorHost SD export guide assets"
  ```

### Task 2: Author the DOCX

**Files:**
- Create: `tools/build_sensorhost_user_guide.py`
- Create: `docs/SensorHost上位机操作指南.docx`

- [ ] **Step 1: Mark the artifact operation**

  ```powershell
  & 'C:\Users\44575\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' container_tools/mark_artifact_operation_started.mjs --operation-kind create --expected-output-count 1 --output-format docx
  ```

- [ ] **Step 2: Build the DOCX**

  Implement `tools/build_sensorhost_user_guide.py` with A4 portrait sections, Chinese styles, a title page, compact feature table, numbered steps, the four verified screenshots, the SD flow image, short notes, and a footer with document title plus page field. Use only absolute source paths resolved from the repository root and save the final DOCX at `docs/SensorHost上位机操作指南.docx`.

- [ ] **Step 3: Run the builder with bundled Python**

  ```powershell
  & 'C:\Users\44575\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' tools/build_sensorhost_user_guide.py
  ```

  Expected: the DOCX exists and contains the expanded SD export/import/playback sections and eight images.

### Task 3: Render and inspect the deliverable

**Files:**
- Read: `docs/SensorHost上位机操作指南.docx`
- Create: `build/docx-qa/sensorhost-guide/page-*.png`

- [ ] **Step 1: Render the DOCX**

  ```powershell
  & 'C:\Users\44575\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' 'C:\Users\44575\.codex\plugins\cache\openai-primary-runtime\documents\26.905.11957\skills\documents\render_docx.py' docs/SensorHost上位机操作指南.docx --output_dir build/docx-qa/sensorhost-guide --emit_pdf
  ```

- [ ] **Step 2: Inspect every rendered page**

  Open each `page-*.png` at full resolution. Verify that captions stay with images, screenshots are not clipped, Chinese glyphs render, tables do not overflow, and the final page does not leave a large orphaned heading.

- [ ] **Step 3: Run structural checks**

  ```powershell
  & 'C:\Users\44575\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' 'C:\Users\44575\.codex\plugins\cache\openai-primary-runtime\documents\26.905.11957\skills\documents\scripts\images_audit.py' docs/SensorHost上位机操作指南.docx
  & 'C:\Users\44575\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' 'C:\Users\44575\.codex\plugins\cache\openai-primary-runtime\documents\26.905.11957\skills\documents\scripts\heading_audit.py' docs/SensorHost上位机操作指南.docx
  ```

- [ ] **Step 4: Fix and re-render if needed**

  If any page has clipping, overlap, unreadable text, or an orphaned caption, adjust the builder and repeat Tasks 2 and 3 until every page passes visual inspection.

### Task 4: Finalize the handoff

**Files:**
- Read: `docs/SensorHost上位机操作指南.docx`
- Read: latest `build/docx-qa/sensorhost-guide/page-*.png`

- [ ] **Step 1: Confirm the requested capabilities are present**

  Confirm the final guide covers interface zones, CDC connection, waveform viewing, RECORD, SD export/download, local playback, and the explicit no-upload boundary.

- [ ] **Step 2: Commit the guide source and artifact**

  ```powershell
  git add tools/build_sensorhost_user_guide.py docs/SensorHost上位机操作指南.docx
  git commit -m "docs: add concise SensorHost operator guide"
  ```
