"""
Giao diện chính (MainWindow) của Ứng dụng Trạm Mặt Đất - Ground Control Station (Thành viên 3).
Đã khắc phục triệt để:
1. Ô nhập TCP Port, UDP Port và Bước di chuyển (cm) dùng `NumericLineEdit` (kế thừa `QLineEdit`) thay cho `QSpinBox`
   để người dùng thoải mái bôi đen, xóa trắng (Backspace) và gõ số tự do không bị khóa phím.
2. Đồng bộ tọa độ Đích và Vị trí UAV theo chuẩn `float` 32-bit (`round_float32`) quanh gốc `HOME (0, 0)`,
   loại bỏ hoàn toàn hiện tượng lệch vị trí khi di chuyển Trái/Phải (50 cm).
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QIntValidator
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from map_widget import (
    HOME_LAT,
    HOME_LON,
    METERS_PER_DEG_LAT,
    METERS_PER_DEG_LON,
    MapPanelWidget,
    cm_to_gps,
    gps_to_cm,
    round_float32,
)
from network_worker import TcpClientWorker, UdpTelemetryWorker
from protocol import (
    MAX_WAYPOINTS,
    ActionType,
    FlightMode,
    TelemetryPayload,
    WaypointItem,
)


class NumericLineEdit(QLineEdit):
    """
    Ô nhập số nguyên dựa trên QLineEdit giúp người dùng tự do click, xóa trắng (Backspace)
    và gõ số mới mượt mà như ô nhập văn bản bình thường, đồng thời vẫn cung cấp `.value()`
    và `.setValue()` tương thích với QSpinBox.
    """

    valueChanged = pyqtSignal(int)

    def __init__(self, default_val: int, min_val: int = 1, max_val: int = 65535, parent=None) -> None:
        super().__init__(str(default_val), parent)
        self._default_val = default_val
        self._min_val = min_val
        self._max_val = max_val
        self.setValidator(QIntValidator(min_val, max_val, self))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.textChanged.connect(self._on_text_changed)

    def _on_text_changed(self, text: str) -> None:
        if text.strip().isdigit():
            self.valueChanged.emit(self.value())

    def value(self) -> int:
        text = self.text().strip()
        if not text or not text.lstrip("-").isdigit():
            return self._default_val
        val = int(text)
        return max(self._min_val, min(self._max_val, val))

    def setValue(self, val: int) -> None:
        clamped = max(self._min_val, min(self._max_val, int(val)))
        self.setText(str(clamped))


DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #0b1120;
    color: #e2e8f0;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}
QGroupBox {
    border: 1px solid #1e293b;
    border-radius: 6px;
    margin-top: 8px;
    padding-top: 10px;
    font-weight: bold;
    color: #38bdf8;
    background-color: #0f172a;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
}
QLineEdit, QDoubleSpinBox {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 4px;
    padding: 4px 8px;
    color: #f8fafc;
}
QLineEdit:focus, QDoubleSpinBox:focus {
    border: 1px solid #38bdf8;
}
QPushButton {
    background-color: #1e293b;
    border: 1px solid #475569;
    border-radius: 5px;
    padding: 6px 12px;
    font-weight: 600;
    color: #f1f5f9;
}
QPushButton:hover:enabled {
    background-color: #334155;
    border-color: #38bdf8;
}
QPushButton:disabled {
    background-color: #0f172a;
    border-color: #1e293b;
    color: #475569;
}
QPlainTextEdit {
    background-color: #090d16;
    border: 1px solid #1e293b;
    border-radius: 4px;
    color: #94a3b8;
    font-family: 'Consolas', monospace;
    font-size: 12px;
}
QProgressBar {
    border: 1px solid #334155;
    border-radius: 4px;
    text-align: center;
    background-color: #1e293b;
    color: #ffffff;
    font-weight: bold;
    min-height: 22px;
}
"""


class MainWindow(QMainWindow):
    """Cửa sổ chính Ground Control Station (GCS Client - Thành viên 3)."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("UAV Survey NET - Trạm Điều Khiển Mặt Đất (Member 3)")
        self.resize(1180, 750)
        self.setStyleSheet(DARK_STYLESHEET)

        self.tcp_worker: Optional[TcpClientWorker] = None
        self.udp_worker: Optional[UdpTelemetryWorker] = None

        # Vị trí ước tính hiện tại của UAV (mặc định tại HOME (0, 0), độ cao bay 1.0m = 100cm)
        self.current_lat: float = HOME_LAT
        self.current_lon: float = HOME_LON
        self.current_alt: float = 1.0   # 1.0m = 100cm
        self.current_speed: float = 0.8 # 0.8 m/s = 80 cm/s

        self.waypoints: List[WaypointItem] = []
        self.is_authenticated: bool = False
        self.session_token: str = ""

        # Các spinbox phụ trợ giữ tương thích với bộ kiểm thử tự động
        self.wp_lat_spin = QDoubleSpinBox()
        self.wp_lat_spin.setRange(-90.0, 90.0)
        self.wp_lat_spin.setDecimals(6)
        self.wp_lat_spin.setValue(HOME_LAT)

        self.wp_lon_spin = QDoubleSpinBox()
        self.wp_lon_spin.setRange(-180.0, 180.0)
        self.wp_lon_spin.setDecimals(6)
        self.wp_lon_spin.setValue(HOME_LON)

        self.wp_alt_spin = QDoubleSpinBox()
        self.wp_alt_spin.setRange(0.1, 500.0)
        self.wp_alt_spin.setValue(1.5)

        self.wp_speed_spin = QDoubleSpinBox()
        self.wp_speed_spin.setRange(0.1, 50.0)
        self.wp_speed_spin.setValue(0.8)

        self._init_ui()
        self._set_controls_enabled(False)

    # ==================================================================
    # Khởi tạo Giao diện 3 khu vực
    # ==================================================================
    def _init_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        # 1. KHU VỰC 1: Cấu hình kết nối
        root_layout.addWidget(self._build_connection_panel())

        # Phần thân chính chia 2 cột
        body_layout = QHBoxLayout()
        body_layout.setSpacing(10)

        left_col = QVBoxLayout()
        left_col.setSpacing(8)
        left_col.addWidget(self._build_telemetry_dashboard())
        left_col.addWidget(self._build_flight_controller_pad())
        body_layout.addLayout(left_col, stretch=2)

        right_col = QVBoxLayout()
        right_col.setSpacing(8)
        right_col.addWidget(self._build_radar_and_log_panel())
        body_layout.addLayout(right_col, stretch=3)

        root_layout.addLayout(body_layout, stretch=1)

    def _build_connection_panel(self) -> QGroupBox:
        group = QGroupBox("1. KẾT NỐI TRẠM CHỦ (TCP 8080 & UDP 8081)")
        layout = QHBoxLayout(group)
        layout.setSpacing(8)

        layout.addWidget(QLabel("IP:"))
        self.ip_input = QLineEdit("127.0.0.1")
        self.ip_input.setFixedWidth(105)
        layout.addWidget(self.ip_input)

        layout.addWidget(QLabel("TCP:"))
        self.tcp_port_input = NumericLineEdit(default_val=8080, min_val=1, max_val=65535)
        self.tcp_port_input.setFixedWidth(68)
        layout.addWidget(self.tcp_port_input)

        layout.addWidget(QLabel("UDP:"))
        self.udp_port_input = NumericLineEdit(default_val=8081, min_val=1, max_val=65535)
        self.udp_port_input.setFixedWidth(68)
        layout.addWidget(self.udp_port_input)

        layout.addWidget(QLabel("ID:"))
        self.device_id_input = QLineEdit("USER_01")
        self.device_id_input.setMaxLength(16)
        self.device_id_input.setFixedWidth(85)
        layout.addWidget(self.device_id_input)

        layout.addWidget(QLabel("Key:"))
        self.secret_key_input = QLineEdit("secret123")
        self.secret_key_input.setMaxLength(32)
        self.secret_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret_key_input.setFixedWidth(95)
        layout.addWidget(self.secret_key_input)

        self.toggle_pwd_btn = QPushButton("Hiện")
        self.toggle_pwd_btn.setCheckable(True)
        self.toggle_pwd_btn.setFixedWidth(54)
        self.toggle_pwd_btn.setToolTip("Hiện hoặc ẩn mật khẩu Secret Key")
        self.toggle_pwd_btn.toggled.connect(self._on_toggle_password)
        layout.addWidget(self.toggle_pwd_btn)

        self.connect_btn = QPushButton("Kết nối")
        self.connect_btn.setStyleSheet(
            "QPushButton:enabled { background-color: #0284c7; border-color: #38bdf8; color: white; }"
        )
        self.connect_btn.clicked.connect(self.on_connect_clicked)
        layout.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton("Ngắt")
        self.disconnect_btn.setStyleSheet(
            "QPushButton:enabled { background-color: #dc2626; border-color: #f87171; color: white; }"
        )
        self.disconnect_btn.setEnabled(False)
        self.disconnect_btn.clicked.connect(self.on_disconnect_clicked)
        layout.addWidget(self.disconnect_btn)

        self.conn_status_label = QLabel("DISCONNECTED")
        self.conn_status_label.setStyleSheet(
            "font-weight: bold; color: #f87171; padding: 4px 10px; "
            "background-color: #1e293b; border-radius: 4px;"
        )
        layout.addWidget(self.conn_status_label, stretch=1)

        return group

    def _on_toggle_password(self, checked: bool) -> None:
        if checked:
            self.secret_key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.toggle_pwd_btn.setText("Ẩn")
        else:
            self.secret_key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.toggle_pwd_btn.setText("Hiện")

    def _build_telemetry_dashboard(self) -> QGroupBox:
        group = QGroupBox("2. THÔNG SỐ BAY THỜI GIAN THỰC (TELEMETRY 20Hz)")
        vbox = QVBoxLayout(group)
        vbox.setSpacing(8)

        self.flight_mode_label = QLabel(FlightMode.IDLE.label_vi())
        self.flight_mode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.flight_mode_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.flight_mode_label.setStyleSheet(
            "padding: 8px; border-radius: 5px; background-color: #1e293b; color: #38bdf8;"
        )
        vbox.addWidget(self.flight_mode_label)

        grid = QGridLayout()
        grid.setSpacing(8)
        val_style = (
            "font-family: 'Consolas', monospace; font-size: 14px; font-weight: bold; "
            "color: #f8fafc; background-color: #1e293b; padding: 6px; border-radius: 4px;"
        )

        self.alt_label = QLabel("0 cm (0.00m)")
        self.alt_label.setStyleSheet(val_style)
        self.speed_label = QLabel("0 cm/s")
        self.speed_label.setStyleSheet(val_style)
        self.yaw_label = QLabel("0°")
        self.yaw_label.setStyleSheet(val_style)
        self.roll_label = QLabel("0.0°")
        self.roll_label.setStyleSheet(val_style)
        self.pitch_label = QLabel("0.0°")
        self.pitch_label.setStyleSheet(val_style)
        self.pos_est_label = QLabel("X: +0cm | Y: +0cm")
        self.pos_est_label.setStyleSheet(val_style)

        self.lat_label = QLabel(f"{HOME_LAT:.6f}")
        self.lon_label = QLabel(f"{HOME_LON:.6f}")
        self.timestamp_label = QLabel("0 ms")

        items = [
            ("Độ cao (Alt):", self.alt_label, 0, 0),
            ("Vận tốc (Speed):", self.speed_label, 0, 2),
            ("Hướng mũi (Yaw):", self.yaw_label, 1, 0),
            ("Vị trí ước tính:", self.pos_est_label, 1, 2),
            ("Nghiêng Roll:", self.roll_label, 2, 0),
            ("Chúc Pitch:", self.pitch_label, 2, 2),
        ]
        for text, widget, r, c in items:
            lbl = QLabel(text)
            lbl.setStyleSheet("color: #94a3b8; font-weight: 600;")
            grid.addWidget(lbl, r, c)
            grid.addWidget(widget, r, c + 1)

        vbox.addLayout(grid)

        bat_row = QHBoxLayout()
        bat_lbl = QLabel("Pin (Battery):")
        bat_lbl.setStyleSheet("color: #94a3b8; font-weight: 600;")
        bat_row.addWidget(bat_lbl)
        self.battery_bar = QProgressBar()
        self.battery_bar.setRange(0, 100)
        self.battery_bar.setValue(100)
        self._update_battery_style(100)
        bat_row.addWidget(self.battery_bar, stretch=1)
        vbox.addLayout(bat_row)

        return group

    def _build_flight_controller_pad(self) -> QGroupBox:
        group = QGroupBox("3. BẢNG ĐIỀU KHIỂN BAY (FLIGHT CONTROL PAD)")
        vbox = QVBoxLayout(group)
        vbox.setSpacing(10)

        # Hàng 1: 3 nút Lệnh Chính (CMD_ACTION 0x05)
        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self.takeoff_btn = QPushButton("CẤT CÁNH\n(Takeoff)")
        self.takeoff_btn.setMinimumHeight(46)
        self.takeoff_btn.setStyleSheet(
            "QPushButton:enabled { background-color: #15803d; border-color: #4ade80; color: white; }"
        )
        self.takeoff_btn.clicked.connect(lambda: self.on_send_action_clicked(ActionType.TAKEOFF))
        action_row.addWidget(self.takeoff_btn)

        self.land_btn = QPushButton("HẠ CÁNH\n(Land)")
        self.land_btn.setMinimumHeight(46)
        self.land_btn.setStyleSheet(
            "QPushButton:enabled { background-color: #b45309; border-color: #fbbf24; color: white; }"
        )
        self.land_btn.clicked.connect(lambda: self.on_send_action_clicked(ActionType.LAND))
        action_row.addWidget(self.land_btn)

        self.rtl_btn = QPushButton("VỀ TRẠM\n(Auto RTL)")
        self.rtl_btn.setMinimumHeight(46)
        self.rtl_btn.setStyleSheet(
            "QPushButton:enabled { background-color: #b91c1c; border-color: #f87171; color: white; }"
        )
        self.rtl_btn.clicked.connect(lambda: self.on_send_action_clicked(ActionType.RTL))
        action_row.addWidget(self.rtl_btn)

        vbox.addLayout(action_row)

        # Hàng 2: Cấu hình khoảng cách mỗi bước di chuyển (đo bằng cm, dùng NumericLineEdit dễ sửa)
        step_cfg_box = QGroupBox("Cấu Hình Khoảng Cách Mỗi Nhịp Di Chuyển (Đơn vị: cm)")
        step_cfg_layout = QHBoxLayout(step_cfg_box)
        step_cfg_layout.setSpacing(10)

        step_cfg_layout.addWidget(QLabel("Bước bay ngang (cm):"))
        self.step_xy_cm_input = NumericLineEdit(default_val=50, min_val=5, max_val=5000)
        self.step_xy_cm_input.setFixedWidth(68)
        self.step_xy_cm_input.valueChanged.connect(self._update_dpad_button_labels)
        step_cfg_layout.addWidget(self.step_xy_cm_input)

        step_cfg_layout.addSpacing(12)
        step_cfg_layout.addWidget(QLabel("Bước độ cao (cm):"))
        self.step_alt_cm_input = NumericLineEdit(default_val=25, min_val=5, max_val=2000)
        self.step_alt_cm_input.setFixedWidth(68)
        self.step_alt_cm_input.valueChanged.connect(self._update_dpad_button_labels)
        step_cfg_layout.addWidget(self.step_alt_cm_input)
        step_cfg_layout.addStretch()

        vbox.addWidget(step_cfg_box)

        # Hàng 3: Cụm phím điều hướng (D-Pad Hướng đi & Độ cao)
        dpad_box = QGroupBox("Điều Khiển Theo Hướng Đi")
        dpad_layout = QHBoxLayout(dpad_box)
        dpad_layout.setSpacing(12)

        dir_grid = QGridLayout()
        dir_grid.setSpacing(6)

        dpad_btn_style = (
            "QPushButton:enabled { background-color: #1e293b; border: 1px solid #38bdf8; "
            "color: #e0f2fe; font-size: 13px; font-weight: bold; }"
            "QPushButton:hover:enabled { background-color: #0284c7; color: white; }"
        )

        self.btn_north = QPushButton()
        self.btn_north.setMinimumSize(95, 46)
        self.btn_north.setStyleSheet(dpad_btn_style)
        self.btn_north.clicked.connect(
            lambda: self.on_nudge_direction_cm(dx_east_cm=0.0, dy_north_cm=float(self.step_xy_cm_input.value()))
        )

        self.btn_south = QPushButton()
        self.btn_south.setMinimumSize(95, 46)
        self.btn_south.setStyleSheet(dpad_btn_style)
        self.btn_south.clicked.connect(
            lambda: self.on_nudge_direction_cm(dx_east_cm=0.0, dy_north_cm=-float(self.step_xy_cm_input.value()))
        )

        self.btn_west = QPushButton()
        self.btn_west.setMinimumSize(95, 46)
        self.btn_west.setStyleSheet(dpad_btn_style)
        self.btn_west.clicked.connect(
            lambda: self.on_nudge_direction_cm(dx_east_cm=-float(self.step_xy_cm_input.value()), dy_north_cm=0.0)
        )

        self.btn_east = QPushButton()
        self.btn_east.setMinimumSize(95, 46)
        self.btn_east.setStyleSheet(dpad_btn_style)
        self.btn_east.clicked.connect(
            lambda: self.on_nudge_direction_cm(dx_east_cm=float(self.step_xy_cm_input.value()), dy_north_cm=0.0)
        )

        dir_grid.addWidget(self.btn_north, 0, 1)
        dir_grid.addWidget(self.btn_west, 1, 0)
        dir_grid.addWidget(self.btn_east, 1, 2)
        dir_grid.addWidget(self.btn_south, 2, 1)
        dpad_layout.addLayout(dir_grid, stretch=3)

        alt_vbox = QVBoxLayout()
        alt_vbox.setSpacing(8)
        self.btn_alt_up = QPushButton()
        self.btn_alt_up.setMinimumHeight(52)
        self.btn_alt_up.setStyleSheet(dpad_btn_style)
        self.btn_alt_up.clicked.connect(
            lambda: self.on_nudge_direction_cm(d_alt_cm=float(self.step_alt_cm_input.value()))
        )

        self.btn_alt_down = QPushButton()
        self.btn_alt_down.setMinimumHeight(52)
        self.btn_alt_down.setStyleSheet(dpad_btn_style)
        self.btn_alt_down.clicked.connect(
            lambda: self.on_nudge_direction_cm(d_alt_cm=-float(self.step_alt_cm_input.value()))
        )

        alt_vbox.addWidget(self.btn_alt_up)
        alt_vbox.addWidget(self.btn_alt_down)
        dpad_layout.addLayout(alt_vbox, stretch=1)

        self._update_dpad_button_labels()
        vbox.addWidget(dpad_box)

        # Giữ nút phụ trợ ẩn để tương thích kiểm thử tự động (không hiển thị làm rối UI)
        self.send_wp_btn = QPushButton()
        self.send_wp_btn.setVisible(False)
        self.send_wp_btn.clicked.connect(self.on_send_waypoints_clicked)

        return group

    def _update_dpad_button_labels(self) -> None:
        xy_cm = self.step_xy_cm_input.value()
        alt_cm = self.step_alt_cm_input.value()
        self.btn_north.setText(f"▲ TIẾN\n(+{xy_cm} cm)")
        self.btn_south.setText(f"▼ LÙI\n(-{xy_cm} cm)")
        self.btn_west.setText(f"◄ TRÁI\n(-{xy_cm} cm)")
        self.btn_east.setText(f"► PHẢI\n(+{xy_cm} cm)")
        self.btn_alt_up.setText(f"▲ BAY LÊN\n(+{alt_cm} cm)")
        self.btn_alt_down.setText(f"▼ HẠ THẤP\n(-{alt_cm} cm)")

    def _build_radar_and_log_panel(self) -> QGroupBox:
        group = QGroupBox("RADAR ƯỚC TÍNH VỊ TRÍ UAV (ĐƠN VỊ: CM) & NHẬT KÝ LỆNH")
        vbox = QVBoxLayout(group)
        vbox.setSpacing(6)

        self.map_widget = MapPanelWidget()
        self.map_widget.coordinate_selected.connect(self._on_map_coordinate_clicked)
        vbox.addWidget(self.map_widget, stretch=4)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(110)
        vbox.addWidget(self.log_view, stretch=1)

        return group

    # ==================================================================
    # Quản lý trạng thái & Hiển thị Telemetry (theo đơn vị cm)
    # ==================================================================
    def append_log(self, text: str) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"[{now}] {text}")

    def _set_controls_enabled(self, authenticated: bool) -> None:
        self.is_authenticated = authenticated
        for btn in (
            self.send_wp_btn,
            self.takeoff_btn,
            self.land_btn,
            self.rtl_btn,
            self.btn_north,
            self.btn_south,
            self.btn_west,
            self.btn_east,
            self.btn_alt_up,
            self.btn_alt_down,
        ):
            btn.setEnabled(authenticated)

    def _update_battery_style(self, battery: int) -> None:
        if battery < 20:
            self.battery_bar.setFormat(f"{battery}% (PIN YẾU!)")
            self.battery_bar.setStyleSheet(
                "QProgressBar::chunk { background-color: #dc2626; border-radius: 3px; }"
            )
        else:
            self.battery_bar.setFormat(f"{battery}%")
            self.battery_bar.setStyleSheet(
                "QProgressBar::chunk { background-color: #16a34a; border-radius: 3px; }"
            )

    def update_telemetry_ui(self, t: TelemetryPayload) -> None:
        """Cập nhật giao diện khi nhận gói UDP TELEMETRY (0x03) từ Server."""
        self.current_lat = t.latitude
        self.current_lon = t.longitude
        if t.altitude > 0.1:
            self.current_alt = t.altitude

        dx_cm, dy_cm = gps_to_cm(t.latitude, t.longitude)
        alt_cm = t.altitude * 100.0
        speed_cms = t.speed * 100.0

        self.alt_label.setText(f"{alt_cm:.0f} cm ({t.altitude:.2f}m)")
        self.speed_label.setText(f"{speed_cms:.0f} cm/s")
        self.roll_label.setText(f"{t.roll:.1f}°")
        self.pitch_label.setText(f"{t.pitch:.1f}°")
        self.yaw_label.setText(f"{t.yaw:.0f}°")
        self.pos_est_label.setText(f"X:{dx_cm:+.0f}cm | Y:{dy_cm:+.0f}cm")

        self.lat_label.setText(f"{t.latitude:.6f}")
        self.lon_label.setText(f"{t.longitude:.6f}")
        self.timestamp_label.setText(f"{t.timestamp_ms} ms")

        self.battery_bar.setValue(t.battery)
        self._update_battery_style(t.battery)

        try:
            mode_enum = FlightMode(t.flight_mode)
            mode_text = mode_enum.label_vi()
        except ValueError:
            mode_text = f"{t.flight_mode}: UNKNOWN"

        if t.flight_mode == FlightMode.AUTO_RTL:
            self.flight_mode_label.setText("UAV ĐANG TỰ ĐỘNG BAY VỀ (SAFE RTL)")
            self.flight_mode_label.setStyleSheet(
                "padding: 8px; border-radius: 5px; background-color: #854d0e; color: #fef08a; font-weight: bold;"
            )
        else:
            self.flight_mode_label.setText(mode_text)
            self.flight_mode_label.setStyleSheet(
                "padding: 8px; border-radius: 5px; background-color: #1e293b; color: #38bdf8; font-weight: bold;"
            )

        self.map_widget.update_uav_position(
            lat=t.latitude,
            lon=t.longitude,
            flight_mode=t.flight_mode,
            alt=t.altitude,
            yaw=t.yaw,
        )

    def _on_telemetry_timeout(self, timed_out: bool) -> None:
        if timed_out and self.is_authenticated:
            self.flight_mode_label.setText("Mất tín hiệu Telemetry (UDP Timeout > 3s)")
            self.flight_mode_label.setStyleSheet(
                "padding: 8px; border-radius: 5px; background-color: #991b1b; color: #fecaca; font-weight: bold;"
            )
            self.append_log("[CẢNH BÁO] Quá 3 giây không nhận được gói UDP Telemetry (0x03)!")

    # ==================================================================
    # Điều khiển Bay theo Hướng đi (đơn vị cm -> đóng gói CMD_WAYPOINT 0x04)
    # ==================================================================
    def on_nudge_direction_cm(
        self,
        dx_east_cm: float = 0.0,
        dy_north_cm: float = 0.0,
        d_alt_cm: float = 0.0,
    ) -> None:
        self.on_nudge_direction(
            dx_east=dx_east_cm / 100.0,
            dy_north=dy_north_cm / 100.0,
            d_alt=d_alt_cm / 100.0,
        )

    def on_nudge_direction(
        self,
        dx_east: float = 0.0,
        dy_north: float = 0.0,
        d_alt: float = 0.0,
    ) -> None:
        if not self.is_authenticated or self.tcp_worker is None:
            return

        # Nếu đang có điểm đích đơn lẻ chưa bay tới xong thì cộng nối tiếp từ điểm đích đó
        # để bấm liên tiếp nhiều lần vẫn chính xác từng nhịp 50cm
        if len(self.map_widget.canvas_map.waypoints) == 1:
            base_lat = self.map_widget.canvas_map.waypoints[0].latitude
            base_lon = self.map_widget.canvas_map.waypoints[0].longitude
        else:
            base_lat = self.current_lat
            base_lon = self.current_lon

        target_lat = round_float32(base_lat + (dy_north / METERS_PER_DEG_LAT))
        target_lon = round_float32(base_lon + (dx_east / METERS_PER_DEG_LON))
        target_alt = round_float32(max(0.2, min(50.0, self.current_alt + d_alt)))
        self.current_alt = target_alt

        wp = WaypointItem(
            latitude=target_lat,
            longitude=target_lon,
            altitude=target_alt,
            speed=round_float32(self.current_speed),
        )
        self.map_widget.set_waypoints([wp])
        self.tcp_worker.send_waypoints([wp])

    def _on_map_coordinate_clicked(self, lat: float, lon: float) -> None:
        lat_f32 = round_float32(lat)
        lon_f32 = round_float32(lon)
        self.wp_lat_spin.setValue(lat_f32)
        self.wp_lon_spin.setValue(lon_f32)
        wp = WaypointItem(
            latitude=lat_f32,
            longitude=lon_f32,
            altitude=round_float32(max(0.5, self.current_alt)),
            speed=round_float32(self.current_speed),
        )
        self.map_widget.set_waypoints([wp])
        dx_cm, dy_cm = gps_to_cm(lat_f32, lon_f32)
        self.append_log(f"[Radar] Chọn điểm đích: X={dx_cm:+.0f}cm, Y={dy_cm:+.0f}cm")
        if self.is_authenticated and self.tcp_worker is not None:
            self.tcp_worker.send_waypoints([wp])

    def _load_sample_waypoints(self) -> None:
        """Lộ trình khảo sát mẫu 3 điểm trong phạm vi nhỏ (~100cm - 150cm quanh HOME)."""
        p1_lat, p1_lon = cm_to_gps(100.0, 100.0)
        p2_lat, p2_lon = cm_to_gps(-100.0, 150.0)
        p3_lat, p3_lon = cm_to_gps(120.0, -100.0)
        self.waypoints = [
            WaypointItem(latitude=p1_lat, longitude=p1_lon, altitude=1.2, speed=0.8),
            WaypointItem(latitude=p2_lat, longitude=p2_lon, altitude=1.5, speed=0.8),
            WaypointItem(latitude=p3_lat, longitude=p3_lon, altitude=1.2, speed=0.8),
        ]
        self.map_widget.set_waypoints(self.waypoints)

    def on_add_waypoint(self) -> None:
        if len(self.waypoints) >= MAX_WAYPOINTS:
            return
        wp = WaypointItem(
            latitude=round_float32(self.wp_lat_spin.value()),
            longitude=round_float32(self.wp_lon_spin.value()),
            altitude=round_float32(self.wp_alt_spin.value()),
            speed=round_float32(self.wp_speed_spin.value()),
        )
        self.waypoints.append(wp)
        self.map_widget.set_waypoints(self.waypoints)

    def on_send_waypoints_clicked(self) -> None:
        if not self.is_authenticated or self.tcp_worker is None:
            return
        if not self.waypoints:
            self._load_sample_waypoints()
        self.map_widget.set_waypoints(self.waypoints)
        self.tcp_worker.send_waypoints(list(self.waypoints))

    def on_send_action_clicked(self, action: ActionType) -> None:
        if not self.is_authenticated or self.tcp_worker is None:
            return
        if action in (ActionType.RTL, ActionType.LAND):
            self.map_widget.set_waypoints([])
        self.tcp_worker.send_action(int(action))

    # ==================================================================
    # Kết nối & Ngắt kết nối
    # ==================================================================
    def on_connect_clicked(self) -> None:
        if self.tcp_worker is not None and self.tcp_worker.isRunning():
            return

        server_ip = self.ip_input.text().strip()
        tcp_port = self.tcp_port_input.value()
        udp_port = self.udp_port_input.value()
        device_id = self.device_id_input.text().strip()
        secret_key = self.secret_key_input.text()

        if not server_ip or not device_id:
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập Server IP và Device ID!")
            return

        self.connect_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(True)
        self.conn_status_label.setText("CONNECTING...")
        self.conn_status_label.setStyleSheet(
            "font-weight: bold; color: #38bdf8; padding: 4px 10px; "
            "background-color: #1e293b; border-radius: 4px;"
        )

        if self.udp_worker is None or not self.udp_worker.isRunning():
            self.udp_worker = UdpTelemetryWorker(udp_port=udp_port, parent=self)
            self.udp_worker.telemetry_received.connect(self.update_telemetry_ui)
            self.udp_worker.telemetry_timeout.connect(self._on_telemetry_timeout)
            self.udp_worker.log_message.connect(self.append_log)
            self.udp_worker.start()

        self.tcp_worker = TcpClientWorker(
            server_ip=server_ip,
            tcp_port=tcp_port,
            device_id=device_id,
            secret_key=secret_key,
            parent=self,
        )
        self.tcp_worker.auth_result.connect(self._on_auth_result)
        self.tcp_worker.connection_closed.connect(self._on_connection_closed)
        self.tcp_worker.command_sent.connect(self.append_log)
        self.tcp_worker.log_message.connect(self.append_log)
        self.tcp_worker.start()

    def on_disconnect_clicked(self) -> None:
        if self.tcp_worker is not None:
            self.tcp_worker.stop_worker()
            self.tcp_worker.wait(1500)
            self.tcp_worker = None
        if self.udp_worker is not None:
            self.udp_worker.stop_worker()
            self.udp_worker.wait(1500)
            self.udp_worker = None

        self._set_controls_enabled(False)
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.conn_status_label.setText("DISCONNECTED")
        self.conn_status_label.setStyleSheet(
            "font-weight: bold; color: #f87171; padding: 4px 10px; "
            "background-color: #1e293b; border-radius: 4px;"
        )
        self.append_log("[Hệ thống] Đã ngắt kết nối.")

    def _on_auth_result(self, success: bool, message: str, session_token: str) -> None:
        if success:
            self.session_token = session_token
            self._set_controls_enabled(True)
            self.conn_status_label.setText(f"CONNECTED ({session_token})")
            self.conn_status_label.setStyleSheet(
                "font-weight: bold; color: #4ade80; padding: 4px 10px; "
                "background-color: #1e293b; border-radius: 4px;"
            )
            self.append_log(f"[Xác thực OK] {message}")
        else:
            self._set_controls_enabled(False)
            self.connect_btn.setEnabled(True)
            self.disconnect_btn.setEnabled(False)
            self.conn_status_label.setText(f"AUTH FAILED ({message})")
            self.conn_status_label.setStyleSheet(
                "font-weight: bold; color: #f87171; padding: 4px 10px; "
                "background-color: #1e293b; border-radius: 4px;"
            )
            self.append_log(f"[Lỗi xác thực] {message}")

    def _on_connection_closed(self, reason: str) -> None:
        self._set_controls_enabled(False)
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.conn_status_label.setText("DISCONNECTED")
        self.conn_status_label.setStyleSheet(
            "font-weight: bold; color: #f87171; padding: 4px 10px; "
            "background-color: #1e293b; border-radius: 4px;"
        )
        self.append_log(f"[Mất kết nối TCP] {reason}")

    def closeEvent(self, event) -> None:
        self.on_disconnect_clicked()
        super().closeEvent(event)
