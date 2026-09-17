"""Modal firmware OTA update dialog: package self-check, progress and cancel."""

from __future__ import annotations

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

from sensor_host.ota import OtaPackageError, describe_phase, load_package
from sensor_host.presentation.spacing import SPACE


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

    upload_requested = pyqtSignal(str, str)
    cancel_requested = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("FIRMWARE OTA UPDATE")
        self.setModal(True)
        self.setMinimumWidth(520)
        self._node_id: str | None = None
        self._package_path: str | None = None
        self._package = None
        self._uploading = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE.section, SPACE.section, SPACE.section, SPACE.section)
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
        self.package_edit.setPlaceholderText("选择一个 .ota 固件包")
        self.package_edit.setAccessibleName("OTA package path")
        package_row.addWidget(self.package_edit, stretch=1)
        self.select_button = QPushButton("SELECT .OTA")
        self.select_button.setAccessibleName("Select OTA package")
        self.select_button.clicked.connect(self._choose_package)
        package_row.addWidget(self.select_button)
        layout.addLayout(package_row)

        self.summary_label = QLabel("未选择固件包")
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

    def set_node(self, node_id: str | None) -> None:
        """Bind the dialog to the node that will receive the upload."""
        self._node_id = node_id
        self.node_label.setText(f"TARGET {node_id or '—'}")
        self.start_button.setEnabled(
            self._package_path is not None and node_id is not None and not self._uploading
        )

    def _choose_package(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self, "Select OTA package", "", "OTA packages (*.ota)"
        )
        if path:
            self.load_package_summary(path)

    def load_package_summary(self, path: str) -> bool:
        """Self-check one package and show its manifest summary; return validity."""
        try:
            package = load_package(path)
        except (OtaPackageError, OSError) as error:
            self._package = None
            self._package_path = None
            self.package_edit.setText(path)
            self.summary_label.setText(f"包自检失败：{error}")
            self.start_button.setEnabled(False)
            self.status_label.setText("STATUS PACKAGE REJECTED")
            return False
        self._package = package
        self._package_path = path
        self.package_edit.setText(path)
        target = package.manifest["target_id"].rstrip(b"\0").decode("ascii", "replace")
        self.summary_label.setText(
            f"TARGET {target}\n"
            f"VERSION {package.version_text}\n"
            f"IMAGE SIZE {package.image_size:,} bytes\n"
            f"IMAGE CRC32 {package.crc_text}"
        )
        self.status_label.setText("STATUS 包自检通过，可以开始上传")
        self.start_button.setEnabled(self._node_id is not None and not self._uploading)
        return True

    def _start(self) -> None:
        if self._package_path is None or self._node_id is None or self._uploading:
            return
        self._uploading = True
        self.start_button.setEnabled(False)
        self.select_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress_bar.setRange(0, 0)
        self.status_label.setText(f"STATUS {describe_phase('HANDSHAKE')}")
        self.upload_requested.emit(self._node_id, self._package_path)

    def _cancel(self) -> None:
        if self._node_id is not None:
            self.cancel_requested.emit(self._node_id)
        self.status_label.setText("STATUS 正在取消…")

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
        self.start_button.setEnabled(
            self._package_path is not None and self._node_id is not None
        )

    def reset(self) -> None:
        """Clear the dialog back to its idle no-package state."""
        self._package = None
        self._package_path = None
        self._uploading = False
        self.package_edit.clear()
        self.summary_label.setText("未选择固件包")
        self.status_label.setText("STATUS IDLE")
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.cancel_button.setEnabled(False)
        self.select_button.setEnabled(True)
        self.start_button.setEnabled(False)

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
