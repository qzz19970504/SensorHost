"""Modal firmware OTA update dialog.

Accepts either an already-packaged ``.ota`` file or a raw compiled ``.bin``
image. For a ``.bin`` the host builds the 512-byte manifest and the ``.ota``
package in memory (target/device/address/CRC/package-id all derived
automatically); the only operator input is the ``a.b.c`` app version, which is
pre-filled from the filename when it contains one and is otherwise editable.
"""

from __future__ import annotations

import zlib
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from sensor_host.ota import (
    APP_FLASH_SIZE,
    MIN_APP_IMAGE_SIZE,
    TARGET_ID,
    OtaPackage,
    OtaPackageError,
    build_package,
    describe_phase,
    format_crc,
    is_package_image,
    load_package,
    version_from_text,
)
from sensor_host.presentation.spacing import SPACE


_TARGET_TEXT = TARGET_ID.rstrip(b"\0").decode("ascii", "replace")
_FILE_FILTER = "Firmware (*.bin *.ota);;Raw image (*.bin);;OTA package (*.ota)"
_DEFAULT_VERSION = "0.0.0"
_TERMINAL_STATUSES = frozenset(
    {
        "FAILED",
        "CANCELLED",
        "RECONNECTED",
        "RECONNECT_TIMEOUT",
        "SOURCE_REJECTED",
        "PACKAGE_REJECTED",
    }
)


class OtaDialog(QDialog):
    """Guide one STM32 SD-staged OTA upload over a UART-source (Wi-Fi) node."""

    upload_requested = pyqtSignal(str, object)
    cancel_requested = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("FIRMWARE OTA UPDATE")
        self.setModal(True)
        self.setMinimumWidth(540)
        self._node_id: str | None = None
        self._selected_path: str | None = None
        self._package: OtaPackage | None = None  # set for .ota selections
        self._image_bytes: bytes | None = None  # set for .bin selections
        self._mode: str | None = None  # "ota" | "bin"
        self._uploading = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            SPACE.section, SPACE.section, SPACE.section, SPACE.section
        )
        layout.setSpacing(SPACE.compact)

        heading = QLabel("STM32 固件 OTA（SD 暂存）")
        heading.setProperty("role", "eyebrow")
        layout.addWidget(heading)

        self.node_label = QLabel("TARGET —")
        self.node_label.setProperty("role", "muted")
        layout.addWidget(self.node_label)

        package_row = QHBoxLayout()
        package_row.setSpacing(SPACE.compact)
        self.package_edit = QLineEdit()
        self.package_edit.setReadOnly(True)
        self.package_edit.setPlaceholderText("选择 .bin（上位机自动打包）或 .ota 固件包")
        self.package_edit.setAccessibleName("OTA package path")
        package_row.addWidget(self.package_edit, stretch=1)
        self.select_button = QPushButton("SELECT…")
        self.select_button.setAccessibleName("Select firmware image or package")
        self.select_button.clicked.connect(self._choose_package)
        package_row.addWidget(self.select_button)
        layout.addLayout(package_row)

        version_row = QHBoxLayout()
        version_row.setSpacing(SPACE.compact)
        version_label = QLabel("APP 版本 (a.b.c)")
        version_label.setProperty("role", "control-label")
        self.version_edit = QLineEdit()
        self.version_edit.setAccessibleName("App version")
        self.version_edit.setPlaceholderText(_DEFAULT_VERSION)
        self.version_edit.setEnabled(False)
        self.version_edit.textChanged.connect(self._refresh_preview)
        version_label.setBuddy(self.version_edit)
        version_row.addWidget(version_label)
        version_row.addWidget(self.version_edit, stretch=1)
        self.version_hint = QLabel("选择 .ota 时版本取自 manifest")
        self.version_hint.setProperty("role", "muted")
        version_row.addWidget(self.version_hint)
        layout.addLayout(version_row)

        self.summary_label = QLabel("未选择固件")
        self.summary_label.setProperty("role", "muted")
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.summary_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("STATUS IDLE")
        self.status_label.setProperty("role", "muted")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(SPACE.compact)
        button_row.addStretch(1)
        self.cancel_button = QPushButton("CANCEL")
        self.cancel_button.setProperty("role", "danger")
        self.cancel_button.setEnabled(False)
        self.cancel_button.setAccessibleName("Cancel OTA upload")
        self.cancel_button.clicked.connect(self._cancel)
        button_row.addWidget(self.cancel_button)
        self.start_button = QPushButton("START UPLOAD")
        self.start_button.setProperty("role", "primary")
        self.start_button.setEnabled(False)
        self.start_button.setAccessibleName("Start OTA upload")
        self.start_button.clicked.connect(self._start)
        button_row.addWidget(self.start_button)
        self.close_button = QPushButton("CLOSE")
        self.close_button.clicked.connect(self.close)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

    # ------------------------------------------------------------------ setup

    def set_node(self, node_id: str | None) -> None:
        """Bind the dialog to the node that will receive the upload."""
        self._node_id = node_id
        self.node_label.setText(f"TARGET {node_id or '—'}")
        self._refresh_start_enabled()

    # -------------------------------------------------------------- selection

    def _choose_package(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self, "Select firmware image or package", "", _FILE_FILTER
        )
        if path:
            self.load_package_summary(path)

    def load_package_summary(self, path: str) -> bool:
        """Load a .ota package or a raw .bin image; return whether it is usable."""
        file_path = Path(path)
        self._selected_path = path
        self.package_edit.setText(path)
        try:
            raw = file_path.read_bytes()
        except OSError as error:
            return self._reject_selection(f"无法读取文件：{error}")

        if is_package_image(raw):
            # Already an .ota (or a mislabeled one): manifest is authoritative.
            try:
                package = load_package(path)
            except (OtaPackageError, OSError) as error:
                return self._reject_selection(f"包自检失败：{error}")
            self._mode = "ota"
            self._package = package
            self._image_bytes = None
            self.version_edit.setEnabled(False)
            self.version_edit.setText(package.version_text)
            self.version_hint.setText("版本取自 .ota manifest")
            self.summary_label.setText(
                self._render_summary(
                    package.version_text, package.image_size, package.crc_text
                )
            )
            self.status_label.setText("STATUS 包自检通过，可以开始上传")
            self._refresh_start_enabled()
            return True

        if file_path.suffix.lower() == ".ota":
            try:
                load_package(path)
            except (OtaPackageError, OSError) as error:
                return self._reject_selection(f"包自检失败：{error}")
            return self._reject_selection("无法识别的 .ota 包")

        # Raw compiled image: the host packages it, only the version is needed.
        if not MIN_APP_IMAGE_SIZE <= len(raw) <= APP_FLASH_SIZE:
            return self._reject_selection(
                f"镜像大小 {len(raw)} 超出范围 "
                f"({MIN_APP_IMAGE_SIZE}..{APP_FLASH_SIZE} 字节)"
            )
        self._mode = "bin"
        self._package = None
        self._image_bytes = raw
        parsed_version = version_from_text(file_path.name) or _DEFAULT_VERSION
        self.version_edit.setEnabled(True)
        self.version_edit.setText(parsed_version)
        self.version_hint.setText("从文件名解析，可修改")
        self._refresh_preview()
        self.status_label.setText("STATUS 已读取 bin，将自动打包为 .ota")
        self._refresh_start_enabled()
        return True

    def _reject_selection(self, message: str) -> bool:
        self._mode = None
        self._package = None
        self._image_bytes = None
        self.version_edit.setEnabled(False)
        self.summary_label.setText(message)
        self.status_label.setText("STATUS PACKAGE REJECTED")
        self._refresh_start_enabled()
        return False

    def _refresh_preview(self) -> None:
        if self._mode != "bin" or self._image_bytes is None:
            return
        crc_text = format_crc(zlib.crc32(self._image_bytes) & 0xFFFFFFFF)
        version = self.version_edit.text().strip() or _DEFAULT_VERSION
        self.summary_label.setText(
            self._render_summary(version, len(self._image_bytes), crc_text)
        )

    @staticmethod
    def _render_summary(version: str, size: int, crc_text: str) -> str:
        return (
            f"TARGET {_TARGET_TEXT}\n"
            f"VERSION {version}\n"
            f"IMAGE SIZE {size:,} bytes\n"
            f"IMAGE CRC32 {crc_text}"
        )

    def _refresh_start_enabled(self) -> None:
        ready = (
            self._node_id is not None
            and self._mode in {"ota", "bin"}
            and not self._uploading
        )
        self.start_button.setEnabled(ready)

    # ----------------------------------------------------------------- upload

    def _build_current_package(self) -> OtaPackage:
        if self._mode == "ota" and self._package is not None:
            return self._package
        if self._mode == "bin" and self._image_bytes is not None:
            version = self.version_edit.text().strip() or _DEFAULT_VERSION
            return build_package(self._image_bytes, app_version=version)
        raise OtaPackageError("no firmware selected")

    def _start(self) -> None:
        if self._node_id is None or self._uploading or self._mode is None:
            return
        try:
            package = self._build_current_package()
        except OtaPackageError as error:
            self.status_label.setText(f"STATUS 打包失败：{error}")
            return
        self._uploading = True
        self.start_button.setEnabled(False)
        self.select_button.setEnabled(False)
        self.version_edit.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress_bar.setRange(0, 0)
        self.status_label.setText(f"STATUS {describe_phase('HANDSHAKE')}")
        self.upload_requested.emit(self._node_id, package)

    def _cancel(self) -> None:
        if self._node_id is not None:
            self.cancel_requested.emit(self._node_id)
        self.status_label.setText("STATUS 正在取消…")

    # ------------------------------------------------------- controller feed

    def on_progress(self, node_id: str, sent: int, total: int, phase: str) -> None:
        if node_id != self._node_id:
            return
        if phase == "DATA" and total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(min(sent, total))
            self.status_label.setText(
                f"STATUS {describe_phase(phase)} · {sent:,}/{total:,} 字节"
            )
        else:
            self.progress_bar.setRange(0, 0)
            self.status_label.setText(f"STATUS {describe_phase(phase)}")

    def on_staged(self, node_id: str, version: str, crc: str, matches: bool) -> None:
        if node_id != self._node_id:
            return
        verdict = "与本地包一致" if matches else "警告：与本地包不一致"
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(1000)
        self.status_label.setText(
            f"STATUS 已暂存 VERSION={version} CRC={crc} · {verdict}"
        )

    def on_state(self, node_id: str, status: str, detail: str) -> None:
        if node_id != self._node_id:
            return
        if detail:
            self.status_label.setText(f"STATUS {detail}")
        if status in _TERMINAL_STATUSES:
            self._finish_upload()
        elif status == "WAIT_RESTART":
            self.cancel_button.setEnabled(False)
            self.progress_bar.setRange(0, 0)

    def _finish_upload(self) -> None:
        self._uploading = False
        self.progress_bar.setRange(0, 1000)
        self.cancel_button.setEnabled(False)
        self.select_button.setEnabled(True)
        if self._mode == "bin":
            self.version_edit.setEnabled(True)
        self._refresh_start_enabled()

    def reset(self) -> None:
        """Clear the dialog back to its idle no-selection state."""
        self._selected_path = None
        self._package = None
        self._image_bytes = None
        self._mode = None
        self._uploading = False
        self.package_edit.clear()
        self.version_edit.clear()
        self.version_edit.setEnabled(False)
        self.version_hint.setText("选择 .ota 时版本取自 manifest")
        self.summary_label.setText("未选择固件")
        self.status_label.setText("STATUS IDLE")
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.cancel_button.setEnabled(False)
        self.select_button.setEnabled(True)
        self._refresh_start_enabled()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if self._uploading:
            answer = QMessageBox.warning(
                self,
                "OTA 进行中",
                "上传进行中，关闭将取消本次 OTA 会话。确认关闭？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._cancel()
        super().closeEvent(event)
