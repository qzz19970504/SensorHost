"""SD archive export management and local export library browser."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QPoint, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sensor_host.presentation.app_controller import AppController, SdRecordInfo
from sensor_host.presentation.spacing import SPACE
from sensor_host.presentation.splitter import CapsuleSplitter
from sensor_host.storage import delete_export, scan_exports


_POLL_INTERVAL_MS = 500
_SPEED_EMA_ALPHA = 0.35
_ARCHIVE_SPLIT_SIZES = (380, 190, 330)
_RECORD_COLUMNS = (
    "NODE",
    "SD",
    "USED",
    "RETAINED",
    "EST DURATION",
    "OVERWRITTEN",
    "EXPORT",
)
_LIBRARY_COLUMNS = ("FILE", "EXPORTED (LOCAL)", "SIZE", "DEVICE", "STATUS")

_MOVE_SEMANTICS_WARNING = (
    "Export uses the firmware move semantics: every retained chunk is reclaimed "
    "from the device SD ring once transmitted. After a successful export the SD "
    "ring is empty and the local file becomes the only archive copy. Continue?"
)


def _human_bytes(value: int | None) -> str:
    if value is None:
        return "—"
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024.0 or unit == "GiB":
            return f"{size:,.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024.0
    return f"{size:,.1f} GiB"


def _human_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    minutes, rest = divmod(seconds, 60.0)
    if minutes >= 60.0:
        hours, minutes = divmod(minutes, 60.0)
        return f"{int(hours)}h{int(minutes):02d}m"
    return f"{int(minutes)}m{rest:04.1f}s"


def _local_time_text(iso_utc: str) -> str:
    """Render one stored UTC timestamp in the operator's local timezone."""
    try:
        parsed = datetime.fromisoformat(iso_utc)
    except ValueError:
        return iso_utc
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _card(title: str, actions: QWidget | None = None) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setProperty("card", True)
    layout = QVBoxLayout(frame)
    layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
    layout.setContentsMargins(SPACE.section, SPACE.section, SPACE.section, SPACE.section)
    layout.setSpacing(SPACE.compact)
    header = QHBoxLayout()
    header.setSpacing(SPACE.compact)
    heading = QLabel(title)
    heading.setProperty("role", "card-title")
    header.addWidget(heading)
    header.addStretch(1)
    if actions is not None:
        actions.setProperty("role", "card-actions")
        header.addWidget(actions, alignment=Qt.AlignmentFlag.AlignVCenter)
    layout.addLayout(header)
    return frame, layout


def _centered_item(value: str, role_data: object = None) -> QTableWidgetItem:
    item = QTableWidgetItem(value)
    item.setTextAlignment(
        Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
    )
    if role_data is not None:
        item.setData(Qt.ItemDataRole.UserRole, role_data)
    return item


class ArchiveView(QWidget):
    """Browse device SD virtual records, run exports, and open local archives."""

    export_requested = pyqtSignal(str)
    cancel_requested = pyqtSignal(str)
    refresh_requested = pyqtSignal()
    open_requested = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self._controller: AppController | None = None
        self._export_node_id: str | None = None
        self._export_started_ms = 0
        self._last_bytes = 0
        self._last_bytes_ms = 0
        self._speed_bytes_per_s = 0.0
        root = CapsuleSplitter(Qt.Orientation.Vertical)
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(root)
        records_card = self._create_records_card()
        progress_card = self._create_progress_card()
        library_card = self._create_library_card()
        root.addWidget(records_card)
        root.addWidget(progress_card)
        root.addWidget(library_card)
        root.setStretchFactor(0, 3)
        root.setStretchFactor(1, 0)
        root.setStretchFactor(2, 3)
        root.setChildrenCollapsible(False)
        root.setSizes(list(_ARCHIVE_SPLIT_SIZES))
        self.archive_splitter = root
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self.poll)

    def set_controller(self, controller: AppController) -> None:
        """Attach the acquisition controller and start state polling."""
        self._controller = controller
        self.refresh_library()
        self.poll()
        self._poll_timer.start()

    def poll(self) -> None:
        """Refresh the SD record table and the active export progress."""
        controller = self._controller
        if controller is None:
            return
        self.set_records(controller.sd_records())
        node_id = controller.active_export_node()
        if node_id is None:
            if self._export_node_id is not None:
                self._export_node_id = None
                self.cancel_button.setEnabled(False)
                self.refresh_library()
            return
        if node_id != self._export_node_id:
            self._export_node_id = node_id
            self._export_started_ms = self._now_ms()
            self._last_bytes = 0
            self._last_bytes_ms = 0
            self._speed_bytes_per_s = 0.0
            self.cancel_button.setEnabled(True)
        active, written, total, phase = controller.export_status(node_id)
        self._update_progress(node_id, active, written, total, phase)

    def set_records(self, records: list[SdRecordInfo]) -> None:
        selected_node = self._selected_record_node()
        self.record_table.setRowCount(len(records))
        for row, record in enumerate(records):
            sd_state = "—"
            if record.sd_format_required:
                sd_state = "FORMAT REQUIRED"
            elif record.sd_ready is True:
                sd_state = "READY"
            elif record.sd_ready is False:
                sd_state = "NOT READY"
            used = (
                f"{_human_bytes(record.used_bytes)} / {_human_bytes(record.capacity_bytes)}"
            )
            retained = (
                "—"
                if record.retained_frames is None
                else f"{record.retained_frames:,} frames"
            )
            values = (
                f"{record.alias} · {record.uuid_suffix}",
                sd_state,
                used,
                retained,
                _human_duration(record.estimated_duration_s),
                "—"
                if record.overwritten_frames is None
                else f"{record.overwritten_frames:,}",
                record.export_phase or "—",
            )
            for column, value in enumerate(values):
                item = _centered_item(
                    value,
                    record.node_id if column == 0 else None,
                )
                self.record_table.setItem(row, column, item)
        if selected_node is not None:
            self._select_record_node(selected_node)

    def refresh_library(self) -> None:
        """Rescan the local export directory into the library table."""
        entries = scan_exports()
        self.library_table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            device = entry.alias or (entry.uuid[:8] if entry.uuid else "—")
            values = (
                entry.name,
                _local_time_text(entry.started_utc),
                _human_bytes(entry.bytes_written),
                device,
                entry.status,
            )
            for column, value in enumerate(values):
                item = _centered_item(
                    value,
                    str(entry.path) if column == 0 else None,
                )
                self.library_table.setItem(row, column, item)

    def on_export_finished(self, node_id: str, phase: str, path: str) -> None:
        """Show the terminal export state and rescan the local library."""
        del node_id
        self.progress_status_label.setText(f"STATUS {phase}")
        self.progress_hint_label.setText(f"saved to {path}")
        self.cancel_button.setEnabled(False)
        self._export_node_id = None
        self.refresh_library()

    def set_open_busy(self, busy: bool) -> None:
        self.open_button.setEnabled(not busy)
        self.open_button.setText("INDEXING…" if busy else "OPEN FOR PLAYBACK")

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API name
        super().showEvent(event)
        self.refresh_library()
        self.poll()

    def _create_records_card(self) -> QFrame:
        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(SPACE.compact)
        self.record_refresh_button = QPushButton("REFRESH")
        self.record_refresh_button.clicked.connect(self._emit_refresh)
        self.export_button = QPushButton("EXPORT SELECTED")
        self.export_button.setProperty("role", "primary")
        self.export_button.clicked.connect(self._confirm_export)
        actions_layout.addWidget(self.record_refresh_button)
        actions_layout.addWidget(self.export_button)
        card, layout = _card("DEVICE SD RECORDS", actions)
        self.record_table = QTableWidget(0, len(_RECORD_COLUMNS))
        self.record_table.setHorizontalHeaderLabels(_RECORD_COLUMNS)
        self.record_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.record_table.verticalHeader().setVisible(False)
        self.record_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.record_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.record_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.record_table.setMinimumHeight(140)
        layout.addWidget(self.record_table, stretch=1)
        hint = QLabel(
            "One virtual record per connected device: the firmware SD ring holds a "
            "single rolling archive, not separate files. Export downloads the whole "
            "ring in original SDF1 byte order."
        )
        hint.setWordWrap(True)
        hint.setProperty("role", "muted")
        layout.addWidget(hint)
        return card

    def _create_progress_card(self) -> QFrame:
        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        self.cancel_button = QPushButton("CANCEL")
        self.cancel_button.setProperty("role", "danger")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._emit_cancel)
        actions_layout.addWidget(self.cancel_button)
        card, layout = _card("EXPORT PROGRESS", actions)
        self.progress_status_label = QLabel("STATUS IDLE")
        self.progress_status_label.setProperty("role", "eyebrow")
        layout.addWidget(self.progress_status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        self.progress_bytes_label = QLabel("0 B / — · 0 B/s · elapsed 0.0 s")
        self.progress_bytes_label.setProperty("role", "muted")
        layout.addWidget(self.progress_bytes_label)
        self.progress_hint_label = QLabel("no export active")
        self.progress_hint_label.setProperty("role", "muted")
        self.progress_hint_label.setWordWrap(True)
        layout.addWidget(self.progress_hint_label)
        return card

    def _create_library_card(self) -> QFrame:
        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(SPACE.compact)
        self.library_refresh_button = QPushButton("REFRESH")
        self.library_refresh_button.clicked.connect(self.refresh_library)
        self.open_button = QPushButton("OPEN FOR PLAYBACK")
        self.open_button.setProperty("role", "primary")
        self.open_button.clicked.connect(self._emit_open)
        actions_layout.addWidget(self.library_refresh_button)
        actions_layout.addWidget(self.open_button)
        card, layout = _card("LOCAL EXPORT LIBRARY", actions)
        self.library_table = QTableWidget(0, len(_LIBRARY_COLUMNS))
        self.library_table.setHorizontalHeaderLabels(_LIBRARY_COLUMNS)
        self.library_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.library_table.verticalHeader().setVisible(False)
        self.library_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.library_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.library_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.library_table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.library_table.customContextMenuRequested.connect(
            self._show_library_context_menu
        )
        self.library_table.doubleClicked.connect(self._emit_open)
        layout.addWidget(self.library_table, stretch=1)
        return card

    def _update_progress(
        self,
        node_id: str,
        active: bool,
        written: int,
        total: int,
        phase: str | None,
    ) -> None:
        now_ms = self._now_ms()
        if active:
            if self._last_bytes_ms:
                elapsed_s = (now_ms - self._last_bytes_ms) / 1000.0
                if elapsed_s > 0.0:
                    instant = max(0.0, (written - self._last_bytes) / elapsed_s)
                    self._speed_bytes_per_s = (
                        self._speed_bytes_per_s * (1.0 - _SPEED_EMA_ALPHA)
                        + instant * _SPEED_EMA_ALPHA
                    )
            self._last_bytes = written
            self._last_bytes_ms = now_ms
            ratio = min(1.0, written / total) if total > 0 else 0.0
            self.progress_bar.setValue(int(round(ratio * 1000)))
            elapsed_s = (now_ms - self._export_started_ms) / 1000.0
            self.progress_status_label.setText(f"STATUS {phase or 'IN PROGRESS'}")
            self.progress_bytes_label.setText(
                f"{_human_bytes(written)} / {_human_bytes(total)} · "
                f"{_human_bytes(int(self._speed_bytes_per_s))}/s · "
                f"elapsed {elapsed_s:,.1f} s"
            )
            self.progress_hint_label.setText(
                f"exporting {node_id}; the device SD ring clears as chunks transmit"
            )
            return
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.progress_bytes_label.setText(
            f"{_human_bytes(written)} / {_human_bytes(total)} · "
            f"{_human_bytes(int(self._speed_bytes_per_s))}/s"
        )
        self.progress_status_label.setText(f"STATUS {phase or 'IDLE'}")

    def _confirm_export(self) -> None:
        node_id = self._selected_record_node()
        if node_id is None:
            return
        answer = QMessageBox.warning(
            self,
            "EXPORT SD ARCHIVE",
            _MOVE_SEMANTICS_WARNING,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.export_requested.emit(node_id)

    def _emit_refresh(self) -> None:
        self.refresh_requested.emit()
        self.poll()

    def _emit_cancel(self) -> None:
        if self._export_node_id is not None:
            self.cancel_requested.emit(self._export_node_id)

    def _emit_open(self) -> None:
        path_text = self._selected_library_path()
        if path_text:
            self.open_requested.emit(Path(path_text))

    def _show_library_context_menu(self, position: QPoint) -> None:
        index = self.library_table.indexAt(position)
        if index.isValid():
            self.library_table.selectRow(index.row())
        if self._selected_library_path() is None:
            return
        menu = QMenu(self.library_table)
        delete_action = menu.addAction("DELETE SELECTED")
        delete_action.triggered.connect(self._delete_selected_export)
        menu.exec(self.library_table.viewport().mapToGlobal(position))

    def _delete_selected_export(self) -> None:
        path_text = self._selected_library_path()
        if path_text is None:
            return
        path = Path(path_text)
        answer = QMessageBox.question(
            self,
            "DELETE LOCAL EXPORT",
            f"Delete {path.name} and its metadata? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_export(path)
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "DELETE LOCAL EXPORT", str(error))
            return
        self.refresh_library()

    def _selected_record_node(self) -> str | None:
        row = self.record_table.currentRow()
        if row < 0:
            return None
        item = self.record_table.item(row, 0)
        return None if item is None else str(item.data(Qt.ItemDataRole.UserRole))

    def _select_record_node(self, node_id: str) -> None:
        for row in range(self.record_table.rowCount()):
            item = self.record_table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == node_id:
                self.record_table.selectRow(row)
                return

    def _selected_library_path(self) -> str | None:
        row = self.library_table.currentRow()
        if row < 0:
            return None
        item = self.library_table.item(row, 0)
        return None if item is None else str(item.data(Qt.ItemDataRole.UserRole))

    @staticmethod
    def _now_ms() -> int:
        return time.monotonic_ns() // 1_000_000
