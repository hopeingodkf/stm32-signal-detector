import os
import struct
import sys
import time
from collections import deque
from datetime import datetime

import serial
import serial.tools.list_ports
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal, QPointF, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF, QFont, QBrush
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QPushButton, QVBoxLayout, QWidget,
)

PACKET_FORMAT = "<HHHHHHHHHHHBBH"
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)
MAGIC = 0xA5C3
BAUD = 921600

FIELDS = [
    "magic", "raw", "filtered", "level", "deviation", "noise_floor",
    "threshold_on", "threshold_off", "hold_remaining", "fmac_status",
    "adc_errors", "state", "confirm_count", "checksum",
]

STATE_NAMES = ["WAITING", "CONFIRMING", "ACTIVE", "HOLDING"]
STATE_COLORS = ["#5a6472", "#d4a72c", "#3fb950", "#d29922"]

BG = "#0d1117"
PANEL = "#161b22"
GRID = "#21262d"
TEXT = "#c9d1d9"
MUTED = "#8b949e"

COLOR_RAW = "#4a5568"
COLOR_FILTERED = "#58a6ff"
COLOR_LEVEL = "#f0f6fc"
COLOR_TON = "#f85149"
COLOR_TOFF = "#a371f7"
COLOR_DEV = "#39c5cf"
COLOR_LIMIT = "#f85149"

HISTORY = 1500

FULL_SCALE = 32760.0
VREF = 3.3

CSV_COLUMNS = [
    "Time", "Tick", "State", "StateName", "Raw", "Filtered", "Level", "Level_V",
    "Deviation", "NoiseFloor", "T_on", "T_off", "Confirm", "Hold", "FMAC", "ADC_Err",
]

BIN_MAGIC = b"SDET"
BIN_VERSION = 1
BIN_HEADER_SIZE = 64


class SerialReader(QThread):
    packet = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, port):
        super().__init__()
        self.port = port
        self.running = True

    def run(self):
        try:
            link = serial.Serial(self.port, BAUD, timeout=0.2)
        except Exception as error:
            self.failed.emit(str(error))
            return

        buffer = bytearray()
        while self.running:
            try:
                chunk = link.read(2048)
            except Exception as error:
                self.failed.emit(str(error))
                break

            if chunk:
                buffer.extend(chunk)

            while len(buffer) >= PACKET_SIZE:
                if buffer[0] != (MAGIC & 0xFF) or buffer[1] != (MAGIC >> 8):
                    buffer.pop(0)
                    continue
                frame = bytes(buffer[:PACKET_SIZE])
                values = struct.unpack(PACKET_FORMAT, frame)
                item = dict(zip(FIELDS, values))
                if item["checksum"] != (sum(frame[:PACKET_SIZE - 2]) & 0xFFFF):
                    self.packet.emit({"crc_error": True})
                    buffer.pop(0)
                    continue
                del buffer[:PACKET_SIZE]
                item["frame"] = frame
                self.packet.emit(item)

        try:
            link.close()
        except Exception:
            pass

    def stop(self):
        self.running = False
        self.wait(1000)


class Recorder:
    def __init__(self, folder, session, write_csv, write_bin):
        stamp = datetime.now()
        base = "Test {}_{}".format(session, stamp.strftime("%H%M%S"))

        self.csv_file = None
        self.bin_file = None
        self.tick = 0
        self.count = 0
        self.paths = []

        if write_csv:
            path = os.path.join(folder, base + ".csv")
            self.csv_file = open(path, "w", encoding="utf-8-sig", newline="")
            self.csv_file.write(";".join(CSV_COLUMNS) + "\n")
            self.paths.append(path)

        if write_bin:
            path = os.path.join(folder, base + ".bin")
            self.bin_file = open(path, "wb")
            header = bytearray(BIN_HEADER_SIZE)
            header[0:4] = BIN_MAGIC
            struct.pack_into("<HHI", header, 4, BIN_VERSION, PACKET_SIZE, int(stamp.timestamp()))
            name = session.encode("utf-8")[:31]
            header[16:16 + len(name)] = name
            self.bin_file.write(header)
            self.paths.append(path)

    def write(self, packet):
        if self.bin_file is not None:
            self.bin_file.write(packet["frame"])

        if self.csv_file is not None:
            state = packet["state"] % 4
            volts = packet["level"] * VREF / FULL_SCALE
            row = [
                datetime.now().strftime("%H:%M:%S"),
                str(self.tick),
                str(state),
                STATE_NAMES[state],
                str(packet["raw"]),
                str(packet["filtered"]),
                str(packet["level"]),
                "{:.3f}".format(volts).replace(".", ","),
                str(packet["deviation"]),
                str(packet["noise_floor"]),
                str(packet["threshold_on"]),
                str(packet["threshold_off"]),
                str(packet["confirm_count"]),
                str(packet["hold_remaining"]),
                str(packet["fmac_status"]),
                str(packet["adc_errors"]),
            ]
            self.csv_file.write(";".join(row) + "\n")

        self.tick += 10
        self.count += 1

    def close(self):
        for handle in (self.csv_file, self.bin_file):
            if handle is not None:
                handle.close()


class RecordDialog(QDialog):
    def __init__(self, parent, folder):
        super().__init__(parent)
        self.setWindowTitle("Запис вимірювань")
        self.setMinimumWidth(430)
        self.setStyleSheet(
            "QDialog{{background:{bg};}} QLabel{{color:{text};}} "
            "QLineEdit{{background:{panel};color:{text};border:1px solid {grid};"
            "border-radius:4px;padding:5px 7px;}} "
            "QCheckBox{{color:{text};}}".format(bg=BG, text=TEXT, panel=PANEL, grid=GRID)
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(9)

        layout.addWidget(QLabel("Назва сесії"))
        self.name_edit = QLineEdit("detector")
        layout.addWidget(self.name_edit)

        self.preview = QLabel()
        self.preview.setStyleSheet("color:{};".format(MUTED))
        layout.addWidget(self.preview)

        self.csv_box = QCheckBox("CSV  —  для Excel, роздільник «;», десяткова кома")
        self.csv_box.setChecked(True)
        self.bin_box = QCheckBox("BIN  —  сирі пакети, компактно, для переграваня")
        self.bin_box.setChecked(True)
        layout.addWidget(self.csv_box)
        layout.addWidget(self.bin_box)

        folder_row = QHBoxLayout()
        self.folder_label = QLabel(folder)
        self.folder_label.setStyleSheet("color:{};".format(MUTED))
        self.folder_label.setWordWrap(True)
        browse = QPushButton("Папка…")
        browse.setStyleSheet(
            "QPushButton{{background:{panel};color:{text};border:1px solid {grid};"
            "border-radius:4px;padding:5px 12px;}}".format(panel=PANEL, text=TEXT, grid=GRID)
        )
        browse.clicked.connect(self.choose_folder)
        folder_row.addWidget(self.folder_label, 1)
        folder_row.addWidget(browse)
        layout.addLayout(folder_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.folder = folder
        self.name_edit.textChanged.connect(self.update_preview)
        self.update_preview()

    def update_preview(self):
        name = self.name_edit.text().strip() or "detector"
        self.preview.setText("Файл:  Test {}_{}.csv".format(name, datetime.now().strftime("%H%M%S")))

    def choose_folder(self):
        picked = QFileDialog.getExistingDirectory(self, "Папка для запису", self.folder)
        if picked:
            self.folder = picked
            self.folder_label.setText(picked)

    def settings(self):
        return (self.folder,
                self.name_edit.text().strip() or "detector",
                self.csv_box.isChecked(),
                self.bin_box.isChecked())


class TracePlot(QWidget):
    def __init__(self, title, traces, show_states=False):
        super().__init__()
        self.title = title
        self.traces = traces
        self.show_states = show_states
        self.data = {name: deque(maxlen=HISTORY) for name, _, _ in traces}
        self.states = deque(maxlen=HISTORY)
        self.setMinimumHeight(220)

    def append(self, packet):
        for name, _, _ in self.traces:
            self.data[name].append(packet.get(name, 0))
        self.states.append(packet.get("state", 0))

    def clear(self):
        for name in self.data:
            self.data[name].clear()
        self.states.clear()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(PANEL))

        margin_left, margin_top = 56, 26
        margin_right, margin_bottom = 10, 22
        band = 12 if self.show_states else 0

        plot = QRectF(
            margin_left, margin_top,
            max(1, self.width() - margin_left - margin_right),
            max(1, self.height() - margin_top - margin_bottom - band),
        )

        painter.setPen(QColor(TEXT))
        font = QFont("Segoe UI", 9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(margin_left, 17, self.title)

        peak = 1
        for name, _, _ in self.traces:
            if self.data[name]:
                peak = max(peak, max(self.data[name]))
        peak = max(peak, 100)
        top = peak * 1.15

        painter.setPen(QPen(QColor(GRID), 1))
        painter.setFont(QFont("Consolas", 8))
        for step in range(5):
            y = plot.top() + plot.height() * step / 4.0
            painter.setPen(QPen(QColor(GRID), 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(QColor(MUTED))
            painter.drawText(QRectF(0, y - 8, margin_left - 6, 16),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             "{:d}".format(int(top * (4 - step) / 4.0)))

        count = 0
        for name, _, _ in self.traces:
            count = max(count, len(self.data[name]))
        if count < 2:
            return

        span = float(max(count, 2))
        step = max(1, int(count / max(1.0, plot.width())))
        for name, color, width in self.traces:
            values = self.data[name]
            if len(values) < 2:
                continue
            polygon = QPolygonF()
            offset = count - len(values)
            snapshot = list(values)
            for index in range(0, len(snapshot), step):
                value = snapshot[index]
                x = plot.left() + plot.width() * (offset + index) / span
                y = plot.bottom() - plot.height() * min(value, top) / top
                polygon.append(QPointF(x, y))
            pen = QPen(QColor(color), width)
            pen.setCosmetic(True)
            if width < 1.0:
                pen.setStyle(Qt.PenStyle.DashLine)
                pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.drawPolyline(polygon)

        if self.show_states and self.states:
            offset = count - len(self.states)
            y = plot.bottom() + 6
            painter.setPen(Qt.PenStyle.NoPen)
            snapshot = list(self.states)
            width_per = plot.width() / span
            index = 0
            while index < len(snapshot):
                state = snapshot[index]
                run = index
                while run < len(snapshot) and snapshot[run] == state:
                    run += 1
                x = plot.left() + plot.width() * (offset + index) / span
                painter.setBrush(QBrush(QColor(STATE_COLORS[state % 4])))
                painter.drawRect(QRectF(x, y, width_per * (run - index) + 0.6, 8))
                index = run

        legend_x = plot.left() + 6
        painter.setFont(QFont("Consolas", 8))
        for name, color, _ in self.traces:
            painter.setPen(QColor(color))
            text = name
            painter.drawText(int(legend_x), int(plot.top()) + 12, text)
            legend_x += 9 * len(text) + 14


class StatTile(QFrame):
    def __init__(self, caption):
        super().__init__()
        self.setStyleSheet(
            "QFrame{{background:{};border:1px solid {};border-radius:4px;}}".format(PANEL, GRID)
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 7)
        layout.setSpacing(1)

        self.caption = QLabel(caption)
        self.caption.setStyleSheet("color:{};border:none;".format(MUTED))
        self.caption.setFont(QFont("Segoe UI", 8))

        self.value = QLabel("—")
        self.value.setStyleSheet("color:{};border:none;".format(TEXT))
        value_font = QFont("Consolas", 14)
        value_font.setBold(True)
        self.value.setFont(value_font)

        layout.addWidget(self.caption)
        layout.addWidget(self.value)

    def set(self, text, color=TEXT):
        self.value.setText(str(text))
        self.value.setStyleSheet("color:{};border:none;".format(color))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Signal Detector Monitor — STM32G474")
        self.resize(1180, 780)
        self.setStyleSheet("QMainWindow{{background:{};}}".format(BG))

        self.reader = None
        self.recorder = None
        self.packets = 0
        self.crc_errors = 0
        self.window_count = 0
        self.window_start = time.time()
        self.rate = 0.0
        self.last = None
        self.paused = False
        self.record_folder = os.path.dirname(os.path.abspath(__file__))

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(9)

        root.addLayout(self.build_toolbar())

        self.tiles = {}
        root.addLayout(self.build_tiles())

        self.level_plot = TracePlot(
            "LEVEL  ·  raw → FMAC → EMA, з порогами",
            [
                ("raw", COLOR_RAW, 1.0),
                ("filtered", COLOR_FILTERED, 1.4),
                ("level", COLOR_LEVEL, 2.0),
                ("threshold_on", COLOR_TON, 0.5),
                ("threshold_off", COLOR_TOFF, 0.5),
            ],
            show_states=True,
        )
        self.dev_plot = TracePlot(
            "STABILITY  ·  середнє відхилення від рівня",
            [("deviation", COLOR_DEV, 1.6)],
        )

        root.addWidget(self.level_plot, 3)
        root.addWidget(self.dev_plot, 2)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(100)

        self.scan_ports()

    def build_toolbar(self):
        bar = QHBoxLayout()
        bar.setSpacing(8)

        style_box = (
            "QComboBox{{background:{panel};color:{text};border:1px solid {grid};"
            "border-radius:4px;padding:5px 8px;}}"
            "QComboBox QAbstractItemView{{background:{panel};color:{text};"
            "selection-background-color:{grid};}}"
        ).format(panel=PANEL, text=TEXT, grid=GRID)

        style_button = (
            "QPushButton{{background:{panel};color:{text};border:1px solid {grid};"
            "border-radius:4px;padding:6px 16px;}}"
            "QPushButton:hover{{border-color:#58a6ff;}}"
            "QPushButton:disabled{{color:{muted};}}"
        ).format(panel=PANEL, text=TEXT, grid=GRID, muted=MUTED)

        self.port_box = QComboBox()
        self.port_box.setStyleSheet(style_box)
        self.port_box.setMinimumWidth(240)

        self.rescan_button = QPushButton("Оновити")
        self.rescan_button.setStyleSheet(style_button)
        self.rescan_button.clicked.connect(self.scan_ports)

        self.connect_button = QPushButton("Підключити")
        self.connect_button.setStyleSheet(style_button)
        self.connect_button.clicked.connect(self.toggle_connection)

        self.pause_box = QCheckBox("Пауза")
        self.pause_box.setStyleSheet("QCheckBox{{color:{};}}".format(TEXT))
        self.pause_box.stateChanged.connect(self.toggle_pause)

        self.record_button = QPushButton("Запис")
        self.record_button.setStyleSheet(style_button)
        self.record_button.clicked.connect(self.toggle_record)

        self.clear_button = QPushButton("Очистити")
        self.clear_button.setStyleSheet(style_button)
        self.clear_button.clicked.connect(self.clear_plots)

        self.status_label = QLabel("не підключено")
        self.status_label.setStyleSheet("color:{};".format(MUTED))

        bar.addWidget(self.port_box)
        bar.addWidget(self.rescan_button)
        bar.addWidget(self.connect_button)
        bar.addSpacing(12)
        bar.addWidget(self.pause_box)
        bar.addWidget(self.record_button)
        bar.addWidget(self.clear_button)
        bar.addStretch(1)
        bar.addWidget(self.status_label)
        return bar

    def build_tiles(self):
        grid = QGridLayout()
        grid.setSpacing(8)
        captions = [
            ("state", "СТАН"), ("level", "РІВЕНЬ"), ("deviation", "РОЗКИД"),
            ("noise", "ФОН"), ("thresholds", "T_on / T_off"), ("confirm", "ПІДТВЕРДЖЕНО"),
            ("hold", "УТРИМАННЯ"), ("rate", "ПАКЕТІВ/С"), ("errors", "FMAC / ADC / CRC"),
        ]
        for index, (key, caption) in enumerate(captions):
            tile = StatTile(caption)
            self.tiles[key] = tile
            grid.addWidget(tile, 0, index)
        return grid

    def scan_ports(self):
        self.port_box.clear()
        found = list(serial.tools.list_ports.comports())
        for info in found:
            self.port_box.addItem("{}  —  {}".format(info.device, info.description), info.device)
        if not found:
            self.port_box.addItem("портів не знайдено", None)

    def toggle_connection(self):
        if self.reader:
            self.reader.stop()
            self.reader = None
            self.connect_button.setText("Підключити")
            self.status_label.setText("відключено")
            self.status_label.setStyleSheet("color:{};".format(MUTED))
            return

        port = self.port_box.currentData()
        if not port:
            return

        self.reader = SerialReader(port)
        self.reader.packet.connect(self.on_packet)
        self.reader.failed.connect(self.on_failed)
        self.reader.start()

        self.connect_button.setText("Відключити")
        self.status_label.setText("{} @ {}".format(port, BAUD))
        self.status_label.setStyleSheet("color:#3fb950;")
        self.window_start = time.time()
        self.window_count = 0

    def on_failed(self, message):
        self.status_label.setText("помилка: {}".format(message))
        self.status_label.setStyleSheet("color:#f85149;")
        if self.reader:
            self.reader = None
        self.connect_button.setText("Підключити")

    def on_packet(self, packet):
        if packet.get("crc_error"):
            self.crc_errors += 1
            return

        self.packets += 1
        self.window_count += 1
        self.last = packet

        if self.recorder is not None:
            self.recorder.write(packet)

        if not self.paused:
            self.level_plot.append(packet)
            self.dev_plot.append(packet)

    def toggle_pause(self, _state):
        self.paused = self.pause_box.isChecked()

    def clear_plots(self):
        self.level_plot.clear()
        self.dev_plot.clear()
        self.packets = 0
        self.crc_errors = 0

    def toggle_record(self):
        if self.recorder is not None:
            count = self.recorder.count
            paths = self.recorder.paths
            self.recorder.close()
            self.recorder = None
            self.record_button.setText("Запис")
            self.status_label.setText("записано {} рядків → {}".format(
                count, os.path.basename(paths[0]) if paths else "—"))
            self.status_label.setStyleSheet("color:{};".format(TEXT))
            return

        dialog = RecordDialog(self, self.record_folder)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        folder, session, write_csv, write_bin = dialog.settings()
        if not write_csv and not write_bin:
            return

        self.record_folder = folder
        try:
            self.recorder = Recorder(folder, session, write_csv, write_bin)
        except Exception as error:
            self.status_label.setText("не вдалося створити файл: {}".format(error))
            self.status_label.setStyleSheet("color:#f85149;")
            return

        self.record_button.setText("Стоп запис")

    def refresh(self):
        now = time.time()
        if now - self.window_start >= 1.0:
            self.rate = self.window_count / (now - self.window_start)
            self.window_count = 0
            self.window_start = now

        packet = self.last
        if packet:
            state = packet["state"] % 4
            self.tiles["state"].set(STATE_NAMES[state], STATE_COLORS[state])
            self.tiles["level"].set(packet["level"])
            self.tiles["deviation"].set(packet["deviation"])
            self.tiles["noise"].set(packet["noise_floor"])
            self.tiles["thresholds"].set("{} / {}".format(packet["threshold_on"], packet["threshold_off"]))
            self.tiles["confirm"].set(packet["confirm_count"])
            self.tiles["hold"].set(packet["hold_remaining"],
                                   "#d29922" if packet["hold_remaining"] else TEXT)

            broken = packet["fmac_status"] or packet["adc_errors"] or self.crc_errors
            self.tiles["errors"].set(
                "{} / {} / {}".format(packet["fmac_status"], packet["adc_errors"], self.crc_errors),
                "#f85149" if broken else "#3fb950",
            )

        self.tiles["rate"].set("{:.0f}".format(self.rate),
                               "#3fb950" if self.rate > 90 else "#d29922")

        if self.recorder is not None:
            self.record_button.setText("Стоп  ({})".format(self.recorder.count))

        self.level_plot.update()
        self.dev_plot.update()

    def closeEvent(self, event):
        if self.reader:
            self.reader.stop()
        if self.recorder is not None:
            self.recorder.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
