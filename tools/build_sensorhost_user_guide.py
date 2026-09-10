from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
DOCX_PATH = ROOT / "docs" / "SensorHost上位机操作指南.docx"
ASSET_DIR = ROOT / "docs" / "artifacts"

LIVE_SCREENSHOT = ROOT / "docs" / "ui-review-evidence" / "stage-5" / "native-cdc-live.png"
DIAGNOSTICS_SCREENSHOT = ROOT / "docs" / "ui-review-evidence" / "stage-5" / "native-cdc-diagnostics.png"
CONSOLE_SCREENSHOT = ROOT / "docs" / "ui-review-evidence" / "stage-5" / "native-cdc-console.png"
OVERVIEW_SCREENSHOT = ROOT / "docs" / "ui-review-evidence" / "stage-4" / "native-live-1440x900-scale1.5.png"
FLOW_IMAGE = ASSET_DIR / "sensorhost_sd_export_flow.png"
SD_ARCHIVE_SCREENSHOT = ASSET_DIR / "sensorhost_sd_archive_overview.png"
SD_PROGRESS_SCREENSHOT = ASSET_DIR / "sensorhost_sd_export_progress.png"
PLAYBACK_SCREENSHOT = ASSET_DIR / "sensorhost_playback_controls.png"

BLACK = "000000"
TEXT = "202A36"
MUTED = "5B6672"
TEAL = "1DBFB4"
NAVY = "17314D"
PALE_BLUE = "EAF3F8"
PALE_TEAL = "E8F7F5"
GRID = "D9E0E5"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/msyhbd.ttc") if bold else Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ]
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def make_sd_flow_image() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    width, height = 1600, 440
    image = Image.new("RGB", (width, height), "#F6F9FB")
    draw = ImageDraw.Draw(image)
    title_font = _font(34, bold=True)
    box_font = _font(30, bold=True)
    body_font = _font(25)
    small_font = _font(23)

    draw.text((54, 28), "SD 卡基础数据流向", fill="#17314D", font=title_font)
    boxes = [
        (55, 130, 330, 270, "设备 SD 卡", "历史数据"),
        (435, 130, 750, 270, "EXPORT SELECTED", "开始导出"),
        (855, 130, 1190, 270, "电脑本地文件", "export-001.sdf1"),
        (1295, 130, 1545, 270, "OPEN FOR", "PLAYBACK"),
    ]
    fills = ["#E8F7F5", "#17314D", "#EAF3F8", "#E8F7F5"]
    text_colors = ["#17314D", "#FFFFFF", "#17314D", "#17314D"]
    for left, top, right, bottom, heading, sub in boxes:
        draw.rounded_rectangle((left, top, right, bottom), radius=18, fill=fills[len([b for b in boxes if b[0] < left])], outline="#AFC8D5", width=3)
        color = text_colors[len([b for b in boxes if b[0] < left])]
        heading_bbox = draw.textbbox((0, 0), heading, font=box_font)
        heading_x = left + (right - left - (heading_bbox[2] - heading_bbox[0])) / 2
        draw.text((heading_x, top + 32), heading, fill=color, font=box_font)
        sub_bbox = draw.textbbox((0, 0), sub, font=body_font)
        sub_x = left + (right - left - (sub_bbox[2] - sub_bbox[0])) / 2
        draw.text((sub_x, top + 86), sub, fill=color, font=body_font)
    for x in (350, 770, 1210):
        draw.line((x, 200, x + 70, 200), fill="#1DBFB4", width=8)
        draw.polygon([(x + 70, 200), (x + 45, 184), (x + 45, 216)], fill="#1DBFB4")
    draw.text((55, 330), "注意：导出成功后设备 SD 环形存档会被清空，本地文件成为存档副本。", fill="#17314D", font=body_font)
    draw.text((55, 378), "当前版本不支持把电脑本地文件上传回 SD 卡。", fill="#B43E3E", font=small_font)
    image.save(FLOW_IMAGE)


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_border(cell, color: str = GRID, size: str = "6") -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = "w:" + edge
        element = borders.find(qn(tag))
        if element is None:
            element = OxmlElement(tag)
            borders.append(element)
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), size)
        element.set(qn("w:space"), "0")
        element.set(qn("w:color"), color)


def set_cell_margins(cell, top: int = 110, start: int = 140, bottom: int = 110, end: int = 140) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    margins = tc_pr.first_child_found_in("w:tcMar")
    if margins is None:
        margins = OxmlElement("w:tcMar")
        tc_pr.append(margins)
    for side, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = margins.find(qn("w:" + side))
        if node is None:
            node = OxmlElement("w:" + side)
            margins.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_run_font(run, name: str = "Microsoft YaHei", size: float | None = None, bold: bool | None = None, color: str | None = None) -> None:
    run.font.name = name
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), name)
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), name)
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color is not None:
        run.font.color.rgb = RGBColor.from_string(color)


def set_style_font(style, name: str, size: float, color: str = BLACK, bold: bool = False) -> None:
    style.font.name = name
    style._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), name)
    style._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), name)
    style._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), name)
    style.font.size = Pt(size)
    style.font.color.rgb = RGBColor.from_string(color)
    style.font.bold = bold


def clear_paragraph_borders(style) -> None:
    p_pr = style._element.get_or_add_pPr()
    p_bdr = p_pr.find(qn("w:pBdr"))
    if p_bdr is not None:
        p_pr.remove(p_bdr)


def set_keep_with_next(paragraph, value: bool = True) -> None:
    paragraph.paragraph_format.keep_with_next = value


def add_field(paragraph, instruction: str, display: str = "1") -> None:
    run = paragraph.add_run()
    fld_char1 = OxmlElement("w:fldChar")
    fld_char1.set(qn("w:fldCharType"), "begin")
    instr_text = OxmlElement("w:instrText")
    instr_text.set(qn("xml:space"), "preserve")
    instr_text.text = instruction
    fld_char2 = OxmlElement("w:fldChar")
    fld_char2.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = display
    fld_char3 = OxmlElement("w:fldChar")
    fld_char3.set(qn("w:fldCharType"), "end")
    run._r.append(fld_char1)
    run._r.append(instr_text)
    run._r.append(fld_char2)
    run._r.append(text)
    run._r.append(fld_char3)
    set_run_font(run, size=9, color=MUTED)


def style_document(doc: Document) -> None:
    section = doc.sections[0]
    section.top_margin = Cm(1.55)
    section.bottom_margin = Cm(1.35)
    section.left_margin = Cm(1.55)
    section.right_margin = Cm(1.55)
    section.header_distance = Cm(0.7)
    section.footer_distance = Cm(0.7)

    styles = doc.styles
    set_style_font(styles["Normal"], "Microsoft YaHei", 10.5, TEXT)
    styles["Normal"].paragraph_format.space_after = Pt(5)
    styles["Normal"].paragraph_format.line_spacing = 1.15

    set_style_font(styles["Title"], "Microsoft YaHei", 25, BLACK, True)
    clear_paragraph_borders(styles["Title"])
    styles["Title"].paragraph_format.space_after = Pt(8)
    styles["Title"].paragraph_format.keep_with_next = True
    for name, size, before, after in (("Heading 1", 16, 6, 7), ("Heading 2", 12.5, 6, 4)):
        style = styles[name]
        set_style_font(style, "Microsoft YaHei", size, BLACK, True)
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True

    if "Caption" not in styles:
        caption = styles.add_style("Caption", WD_STYLE_TYPE.PARAGRAPH)
    else:
        caption = styles["Caption"]
    set_style_font(caption, "Microsoft YaHei", 9, MUTED)
    caption.paragraph_format.space_before = Pt(2)
    caption.paragraph_format.space_after = Pt(8)
    caption.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER

    footer = section.footer
    footer_p = footer.paragraphs[0]
    footer_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer_p.paragraph_format.space_before = Pt(5)
    footer_p.text = "SensorHost 上位机操作指南  ·  "
    for run in footer_p.runs:
        set_run_font(run, size=9, color=MUTED)
    add_field(footer_p, "PAGE")


def add_body(doc: Document, text: str, *, bold_lead: str | None = None, color: str = TEXT) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(5)
    if bold_lead and text.startswith(bold_lead):
        lead = p.add_run(bold_lead)
        set_run_font(lead, size=10.5, bold=True, color=BLACK)
        rest = p.add_run(text[len(bold_lead):])
        set_run_font(rest, size=10.5, color=color)
    else:
        run = p.add_run(text)
        set_run_font(run, size=10.5, color=color)


def add_step(doc: Document, number: int, title: str, body: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.25)
    p.paragraph_format.first_line_indent = Cm(-0.25)
    p.paragraph_format.space_after = Pt(4)
    n = p.add_run(f"{number}. ")
    set_run_font(n, size=10.5, bold=True, color=TEAL)
    lead = p.add_run(title)
    set_run_font(lead, size=10.5, bold=True, color=BLACK)
    rest = p.add_run(body)
    set_run_font(rest, size=10.5, color=TEXT)


def add_bullet(doc: Document, text: str, color: str = TEXT) -> None:
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.left_indent = Cm(0.5)
    p.paragraph_format.space_after = Pt(3)
    run = p.add_run(text)
    set_run_font(run, size=10.5, color=color)


def add_picture(doc: Document, path: Path, width: float, caption: str) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.keep_with_next = True
    p.add_run().add_picture(str(path), width=Inches(width))
    caption_p = doc.add_paragraph(style="Caption")
    caption_p.add_run(caption)
    for run in caption_p.runs:
        set_run_font(run, size=9, color=MUTED)


def add_heading(doc: Document, text: str, level: int = 1) -> None:
    p = doc.add_heading(text, level=level)
    for run in p.runs:
        set_run_font(run, size=16 if level == 1 else 12.5, bold=True, color=BLACK)


def add_table(doc: Document, headers: list[str], rows: Iterable[list[str]], widths: list[float]) -> None:
    data = list(rows)
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    header_cells = table.rows[0].cells
    for idx, header in enumerate(headers):
        header_cells[idx].width = Inches(widths[idx])
        set_cell_shading(header_cells[idx], NAVY)
        set_cell_border(header_cells[idx])
        set_cell_margins(header_cells[idx])
        header_cells[idx].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        p = header_cells[idx].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_after = Pt(0)
        run = p.add_run(header)
        set_run_font(run, size=9.5, bold=True, color="FFFFFF")
    for row_idx, row in enumerate(data):
        cells = table.add_row().cells
        for col_idx, text in enumerate(row):
            cells[col_idx].width = Inches(widths[col_idx])
            set_cell_shading(cells[col_idx], PALE_BLUE if row_idx % 2 else "FFFFFF")
            set_cell_border(cells[col_idx])
            set_cell_margins(cells[col_idx])
            cells[col_idx].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            p = cells[col_idx].paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            run = p.add_run(text)
            set_run_font(run, size=9.3, color=TEXT)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def add_warning(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(6)
    lead = p.add_run("注意：")
    set_run_font(lead, size=10.5, bold=True, color="B43E3E")
    rest = p.add_run(text)
    set_run_font(rest, size=10.5, color=TEXT)


def build_doc() -> None:
    make_sd_flow_image()
    for path in (
        LIVE_SCREENSHOT,
        DIAGNOSTICS_SCREENSHOT,
        CONSOLE_SCREENSHOT,
        OVERVIEW_SCREENSHOT,
        FLOW_IMAGE,
        SD_ARCHIVE_SCREENSHOT,
        SD_PROGRESS_SCREENSHOT,
        PLAYBACK_SCREENSHOT,
    ):
        if not path.exists():
            raise FileNotFoundError(path)

    doc = Document()
    style_document(doc)

    # Page 1: cover and shortest path.
    title = doc.add_paragraph(style="Title")
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    title.add_run("SensorHost 上位机操作指南")
    for run in title.runs:
        set_run_font(run, size=25, bold=True, color=BLACK)
    subtitle = doc.add_paragraph()
    subtitle.paragraph_format.space_after = Pt(18)
    run = subtitle.add_run("设备连接、实时波形查看与 SD 卡数据导出")
    set_run_font(run, size=13, color=MUTED)

    add_body(doc, "本指南面向第一次使用 SensorHost 的操作人员。按下面的顺序操作，即可完成设备连接、查看实时数据、保存记录，并把设备 SD 卡中的历史数据导出到电脑。")
    add_heading(doc, "最短上手路径", 1)
    add_step(doc, 1, "连接设备。", "选择 CDC，刷新并选择 STM32 的 COM 口，点击 CONNECT。")
    add_step(doc, 2, "开始采集。", "将 LIVE TARGET 设为 CDC，点击 START。")
    add_step(doc, 3, "查看波形。", "在 LIVE MONITOR 中观察 X、Y、Z 三轴曲线和姿态数据。")
    add_step(doc, 4, "需要保存时。", "点击 RECORD 保存实时数据；需要导出 SD 历史数据时，先 STOP，再进入 SD ARCHIVE。")
    add_heading(doc, "使用前准备", 1)
    add_bullet(doc, "STM32 采集板已上电，USB 数据线已连接到电脑。")
    add_bullet(doc, "Windows 设备管理器中能看到 USB 串行设备（COMx）。COM 号可能因电脑或 USB 插口变化。")
    add_bullet(doc, "本指南以 CDC 为例；使用 WI-FI 时选择 WI-FI，并按页面填写网卡和 PC IPv4，确保电脑与设备在同一网络。")
    add_warning(doc, "CONNECT 只建立连接和查询设备，不会自动 START。连接成功后没有波形时，通常还需要选择 LIVE TARGET=CDC 并点击 START。")
    doc.add_page_break()

    # Page 2: interface overview.
    add_heading(doc, "1 界面总览", 1)
    add_body(doc, "上位机按“连接、采集、设备、数据页面”分区。第一次使用时，先看懂这些区域，再按后面的步骤操作。")
    add_picture(doc, OVERVIEW_SCREENSHOT, 6.65, "图 1  上位机主界面示例")
    add_table(
        doc,
        ["功能区", "主要用途"],
        [
            ["顶部连接区", "选择 CDC / WI-FI、选择设备或 COM 口、REFRESH、CONNECT / DISCONNECT。"],
            ["采集工具栏", "设置 WINDOW、FIFO WM、LIVE TARGET，使用 START、STOP、PAUSE、RECORD。"],
            ["DEVICES", "查看已发现设备，点击设备行可切换当前目标；下方可保存设备别名。"],
            ["LIVE MONITOR", "查看 IIS3DWB 三轴振动曲线、JY61PL 姿态和 Stream Health。"],
            ["DIAGNOSTICS", "查看解析器、链路、固件和存储计数器。"],
            ["CONSOLE", "查看设备回复，必要时发送高级 AT 命令。"],
            ["SD ARCHIVE", "查看设备 SD 存档，执行导出，并在本地导出库中打开回放。"],
        ],
        [1.65, 5.0],
    )
    doc.add_page_break()

    # Page 3: connection.
    add_heading(doc, "2 连接设备", 1)
    add_body(doc, "下面以 USB CDC 连接 STM32 为例。连接后还要显式选择 CDC 实时目标并启动采集。")
    add_picture(doc, LIVE_SCREENSHOT, 6.65, "图 2  CDC 连接成功并显示实时数据时的界面")
    add_step(doc, 1, "插入 USB。", "给采集板上电，并用 USB 数据线连接电脑。")
    add_step(doc, 2, "选择 CDC。", "在顶部连接区把通路选择为 CDC。")
    add_step(doc, 3, "刷新端口。", "点击 REFRESH，在设备下拉框中选择 STM32 对应的 USB 串行设备（COMx）。")
    add_step(doc, 4, "建立连接。", "点击 CONNECT。右侧状态显示 CONNECTED，左侧 DEVICES 列表出现设备。")
    add_step(doc, 5, "选择实时目标。", "确认 LIVE TARGET 为 CDC。设备如果原来正在 UART 采集，请先 STOP，等待 IDLE / OK，再切换为 CDC。")
    add_step(doc, 6, "开始采集。", "点击 START，等待 CONSOLE 返回 OK；随后 LIVE MONITOR 开始刷新。")
    add_warning(doc, "如果找不到 COM 口，先点击 REFRESH，并在设备管理器确认实际 COM 号；不要固定假定一定是 COM6。")
    doc.add_page_break()

    # Page 4: waveform and health.
    add_heading(doc, "3 查看波形和判断是否正常", 1)
    add_body(doc, "采集开始后，LIVE MONITOR 是最常用页面。中间的大图是 IIS3DWB 三轴振动，右侧是 JY61PL 姿态和加速度。")
    add_heading(doc, "实时波形区", 2)
    add_bullet(doc, "X、Y、Z：分别显示三个方向的振动曲线；点击曲线按钮可隐藏或显示对应通道。")
    add_bullet(doc, "WINDOW：改变图表显示的时间范围，不影响后台记录文件。")
    add_bullet(doc, "AUTO Y：自动调整纵轴；RESET VIEW：手动缩放或平移后恢复跟随最新数据。")
    add_bullet(doc, "PAUSE：只暂停界面刷新，不停止设备采集，也不停止 RECORD；真正停止采集请点击 STOP。")
    add_heading(doc, "快速判断", 2)
    add_bullet(doc, "SAMPLES/S 持续为非零，曲线向左滚动。")
    add_bullet(doc, "CRC ERR 为 0，SEQ GAP、LINK ERR 在稳定链路下不持续增加。")
    add_bullet(doc, "姿态数据更新频率比振动曲线低，短时间少量更新属于正常现象。")
    add_heading(doc, "诊断与命令回复", 2)
    add_body(doc, "遇到“已连接但没有波形”时，先看 DIAGNOSTICS 的帧数和错误计数，再看 CONSOLE 是否返回 ERROR。")

    # Two compact figures keep the secondary pages readable without forcing a new page.
    image_table = doc.add_table(rows=1, cols=2)
    image_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    image_table.autofit = False
    for idx, (path, caption) in enumerate(
        [
            (DIAGNOSTICS_SCREENSHOT, "图 3  DIAGNOSTICS：帧数、CRC 与设备状态"),
            (CONSOLE_SCREENSHOT, "图 4  CONSOLE：查看 OK、状态和导出回复"),
        ]
    ):
        cell = image_table.rows[0].cells[idx]
        cell.width = Inches(3.25)
        set_cell_border(cell, color="FFFFFF", size="0")
        set_cell_margins(cell, 0, 50, 0, 50)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.keep_with_next = True
        p.add_run().add_picture(str(path), width=Inches(3.15))
        cp = cell.add_paragraph(style="Caption")
        cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cp.add_run(caption)
        for run in cp.runs:
            set_run_font(run, size=8.3, color=MUTED)
    doc.add_page_break()

    # Page 5: recording and SD export.
    add_heading(doc, "4 记录实时数据", 1)
    add_body(doc, "RECORD 保存的是上位机连接后收到的实时 SDF1 数据，和 SD 卡中的历史存档是两条不同的数据路径。")
    add_step(doc, 1, "开始记录。", "设备已连接并有实时数据时，点击 RECORD。按钮保持选中状态，并显示当前记录会话数。")
    add_step(doc, 2, "继续操作。", "查看波形、改变 WINDOW 或 PAUSE 都不会停止后台记录。")
    add_step(doc, 3, "结束记录。", "再次点击 RECORD，等待文件写入完成。")
    add_body(doc, "Windows 默认保存位置：%LOCALAPPDATA%\\SensorHost\\recordings\\<批次>\\<设备>\\。")

    add_heading(doc, "5 SD 卡导出和下载", 1)
    add_body(doc, "SD ARCHIVE 用于把设备 SD 卡中的历史数据导出到电脑。导出前必须先让设备处于 IDLE。")
    add_picture(doc, SD_ARCHIVE_SCREENSHOT, 6.65, "图 5  SD ARCHIVE 页面：设备存档、导出按钮和本地导出库")
    add_step(doc, 1, "先停止采集。", "点击 STOP，等待 CONSOLE 返回 OK，并确认设备状态为 IDLE。")
    add_step(doc, 2, "打开 SD ARCHIVE。", "切换到 SD ARCHIVE 页面，点击 REFRESH 获取设备 SD 状态。")
    add_step(doc, 3, "选择并导出。", "选中目标设备行，点击 EXPORT SELECTED，并确认导出提示。")
    add_step(doc, 4, "查看进度。", "在 EXPORT PROGRESS 中查看已接收字节、速度和状态；导出期间不要 START 或拔线。")
    add_step(doc, 5, "确认本地文件。", "完成后文件会进入 LOCAL EXPORT LIBRARY，状态为 complete 的记录可以继续回放。")
    add_warning(doc, "导出成功后设备 SD 环形存档会被清空，本地文件成为唯一存档副本。当前版本不提供把电脑文件上传回 SD 卡的功能。")

    # Page 6: export progress and import/playback.
    add_heading(doc, "6 查看导出进度", 1)
    add_body(doc, "导出期间，EXPORT PROGRESS 会显示当前状态。正常完成后状态为 COMPLETE；如果中途取消或连接中断，记录会保留相应的中止状态。")
    add_picture(doc, SD_PROGRESS_SCREENSHOT, 6.65, "图 6  导出进行中：查看进度并可取消本次导出")
    add_bullet(doc, "EXPORT PROGRESS：查看接收字节、SD 分配空间、速度和耗时。")
    add_bullet(doc, "CANCEL：需要中止时点击；已接收部分会保留并标记为 aborted。")
    add_bullet(doc, "导出结束后回到 LOCAL EXPORT LIBRARY，优先选择状态为 complete 的文件回放。")

    add_heading(doc, "7 导入导出文件并回放", 1)
    add_body(doc, "这里的“导入”是把电脑上的导出文件打开到上位机进行回放，不会把文件写回设备 SD 卡。导出文件不需要重新连接设备即可回放。")
    add_picture(doc, FLOW_IMAGE, 6.65, "图 7  SD 历史数据导出、导入上位机与回放的数据方向")
    add_picture(doc, PLAYBACK_SCREENSHOT, 6.65, "图 8  回放状态：文件名、播放控制、进度和倍速")
    add_step(doc, 1, "选择文件。", "在 LOCAL EXPORT LIBRARY 中选中状态为 complete 的导出记录。")
    add_step(doc, 2, "打开回放。", "点击 OPEN FOR PLAYBACK，或双击记录行；等待文件索引完成。")
    add_step(doc, 3, "控制播放。", "使用 PLAY / PAUSE、STOP、进度条拖动和 0.5×、1×、2×、4× 速度。")
    add_step(doc, 4, "退出回放。", "点击播放条 STOP，返回实时监看；播放到末尾后再次 PLAY 会从头开始。")

    doc.add_page_break()
    add_heading(doc, "8 安全停止和退出", 1)
    add_body(doc, "建议按以下顺序退出，避免记录文件没有正常收尾：")
    add_step(doc, 1, "停止 RECORD。", "如果 RECORD 正在运行，再次点击 RECORD 完成写盘。")
    add_step(doc, 2, "停止设备采集。", "点击 STOP，等待 CONSOLE 返回 OK。")
    add_step(doc, 3, "断开连接。", "点击 DISCONNECT，再关闭上位机。")
    add_warning(doc, "只关闭串口或直接退出程序不能替代 STOP；设备端可能仍保持采集状态或原来的实时目标。")

    add_heading(doc, "9 两个常见提示", 1)
    add_bullet(doc, "已 CONNECTED 但无曲线：确认左侧选中了在线设备，LIVE TARGET=CDC，且已点击 START；再看 DIAGNOSTICS 的帧数是否增加。")
    add_bullet(doc, "选择 CDC 出现 ERROR:STATE：设备仍在采集或实时目标不是 CDC。按 STOP → 等待 IDLE / OK → 选择 CDC → START 的顺序重试。")
    add_bullet(doc, "不确定当前发生了什么：打开 CONSOLE 查看最近的 OK、ERROR、+STATE 和 EXPORT_* 回复。")

    # Set document core properties without personal author data.
    props = doc.core_properties
    props.title = "SensorHost 上位机操作指南"
    props.subject = "设备连接、实时波形查看与 SD 卡数据导出"
    props.author = ""
    props.last_modified_by = ""
    props.comments = ""
    DOCX_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc.save(DOCX_PATH)


if __name__ == "__main__":
    build_doc()
    print(DOCX_PATH)
