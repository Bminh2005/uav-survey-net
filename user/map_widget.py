"""
Màn hình Radar Ước tính Vị trí UAV (2D Radar Position View - Đơn vị cm cho môi trường Wi-Fi nhỏ).
Lưu ý kỹ thuật quan trọng về độ chính xác số thực 32-bit (`float` `>f` theo giaothuc.pdf):
- Do kiểu `float` 32-bit (IEEE-754) chỉ có 23 bit phần định trị (mantissa), nếu lấy gốc kinh độ ở ~105.8 độ
  thì bước nhảy nhỏ nhất (ULP) của `float` 32-bit là 2^-17 độ (~79.1 cm), gây sai lệch vị trí khi di chuyển 50 cm!
- Vì vậy hệ tọa độ cục bộ trong phòng/sân nhỏ đặt gốc Trạm HOME tại `(0.0, 0.0)` để `float` 32-bit đạt độ chính xác
  tới từng milimet (0.01 cm), đảm bảo vị trí Đích trên UI và vị trí UAV nhận về từ UDP khớp nhau tuyệt đối 100%.
"""

from __future__ import annotations

import math
import struct
from typing import List, Tuple

from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from protocol import WaypointItem

# Đặt gốc tọa độ cục bộ HOME tại (0.0, 0.0) để tránh sai số làm tròn 32-bit float (~79cm ở kinh độ 105)
HOME_LAT: float = 0.0
HOME_LON: float = 0.0
METERS_PER_DEG_LAT: float = 100_000.0  # 1 độ cục bộ = 100,000 m => 1 cm = 1e-7 độ (chính xác tuyệt đối ở float32)
METERS_PER_DEG_LON: float = 100_000.0


def round_float32(val: float) -> float:
    """Chuẩn hóa số thực về đúng giá trị IEEE-754 32-bit float (`>f`) trên đường truyền."""
    return struct.unpack(">f", struct.pack(">f", float(val)))[0]


def gps_to_Lock_meters(lat: float, lon: float) -> Tuple[float, float]:
    """Đổi tọa độ sang khoảng cách mét ước tính (Đông-Tây X, Bắc-Nam Y) so với HOME."""
    dx_east = (lon - HOME_LON) * METERS_PER_DEG_LON
    dy_north = (lat - HOME_LAT) * METERS_PER_DEG_LAT
    return dx_east, dy_north


def gps_to_cm(lat: float, lon: float) -> Tuple[float, float]:
    """Đổi tọa độ sang khoảng cách centimet (cm) ước tính (X, Y) so với HOME."""
    dx_m, dy_m = gps_to_Lock_meters(lat, lon)
    return dx_m * 100.0, dy_m * 100.0


def meters_to_gps(dx_east: float, dy_north: float) -> Tuple[float, float]:
    """Đổi khoảng cách mét ước tính (X, Y) so với HOME sang tọa độ (Lat, Lon) chuẩn float32."""
    lat = round_float32(HOME_LAT + (dy_north / METERS_PER_DEG_LAT))
    lon = round_float32(HOME_LON + (dx_east / METERS_PER_DEG_LON))
    return lat, lon


def cm_to_gps(dx_east_cm: float, dy_north_cm: float) -> Tuple[float, float]:
    """Đổi khoảng cách centimet (cm) ước tính (X, Y) so với HOME sang tọa độ (Lat, Lon) chuẩn float32."""
    return meters_to_gps(dx_east_cm / 100.0, dy_north_cm / 100.0)


class TacticalCanvasMap(QWidget):
    """Màn hình Radar 2D hiển thị vị trí ước tính của UAV (đơn vị cm) so với Trạm gốc (HOME)."""

    coordinate_clicked = pyqtSignal(float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(420, 360)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self.uav_lat: float = HOME_LAT
        self.uav_lon: float = HOME_LON
        self.uav_alt: float = 0.0
        self.uav_yaw: float = 0.0
        self.uav_mode: int = 0

        # Phạm vi bán kính hiển thị của Radar (cm) - Mặc định 300 cm (3 mét)
        self.radar_range_cm: float = 300.0
        self.waypoints: List[WaypointItem] = []
        self.trail: List[Tuple[float, float]] = [(HOME_LAT, HOME_LON)]

    def _cm_to_screen(self, dx_cm: float, dy_cm: float) -> QPointF:
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        radius_px = min(self.width(), self.height()) * 0.40
        scale = radius_px / max(self.radar_range_cm, 50.0)
        return QPointF(cx + dx_cm * scale, cy - dy_cm * scale)

    def _gps_to_screen(self, lat: float, lon: float) -> QPointF:
        dx_cm, dy_cm = gps_to_cm(lat, lon)
        return self._cm_to_screen(dx_cm, dy_cm)

    def _screen_to_gps(self, sx: float, sy: float) -> Tuple[float, float]:
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        radius_px = min(self.width(), self.height()) * 0.40
        scale = radius_px / max(self.radar_range_cm, 50.0)
        dx_cm = (sx - cx) / scale
        dy_cm = (cy - sy) / scale
        return cm_to_gps(dx_cm, dy_cm)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            lat, lon = self._screen_to_gps(pos.x(), pos.y())
            self.coordinate_clicked.emit(lat, lon)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Nền Radar tối
        painter.fillRect(self.rect(), QColor("#090d16"))

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        radius_px = min(self.width(), self.height()) * 0.40

        # Tự động mở rộng phạm vi Radar nếu UAV hoặc điểm đích nằm xa hơn 300 cm
        uav_dx_cm, uav_dy_cm = gps_to_cm(self.uav_lat, self.uav_lon)
        max_dist_cm = math.hypot(uav_dx_cm, uav_dy_cm)
        for wp in self.waypoints:
            wx, wy = gps_to_cm(wp.latitude, wp.longitude)
            max_dist_cm = max(max_dist_cm, math.hypot(wx, wy))
        self.radar_range_cm = max(300.0, math.ceil((max_dist_cm + 50.0) / 150.0) * 150.0)

        # Vẽ 3 vòng tròn cự ly Radar (theo cm)
        ring_pen = QPen(QColor("#1e293b"), 1, Qt.PenStyle.SolidLine)
        painter.setPen(ring_pen)
        painter.setFont(QFont("Consolas", 8))
        for frac in (1.0 / 3.0, 2.0 / 3.0, 1.0):
            r = radius_px * frac
            painter.drawEllipse(QPointF(cx, cy), r, r)
            ring_dist_cm = int(round(self.radar_range_cm * frac))
            painter.setPen(QColor("#475569"))
            painter.drawText(QPointF(cx + 4, cy - r + 12), f"{ring_dist_cm} cm")
            painter.setPen(ring_pen)

        # Trục Bắc-Nam & Đông-Tây
        painter.drawLine(QPointF(cx - radius_px - 15, cy), QPointF(cx + radius_px + 15, cy))
        painter.drawLine(QPointF(cx, cy - radius_px - 15), QPointF(cx, cy + radius_px + 15))

        # Nhãn 4 hướng
        painter.setPen(QColor("#38bdf8"))
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.drawText(QPointF(cx - 28, cy - radius_px - 20), "TIẾN (Bắc)")
        painter.drawText(QPointF(cx - 26, cy + radius_px + 30), "LÙI (Nam)")
        painter.drawText(QPointF(cx + radius_px + 20, cy + 4), "PHẢI (Đông)")
        painter.drawText(QPointF(cx - radius_px - 75, cy + 4), "TRÁI (Tây)")

        # Vẽ điểm Trạm gốc HOME [H] ở chính giữa
        painter.setPen(QPen(QColor("#94a3b8"), 2))
        painter.setBrush(QBrush(QColor("#334155")))
        painter.drawRect(int(cx - 6), int(cy - 6), 12, 12)
        painter.setPen(QColor("#cbd5e1"))
        painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        painter.drawText(QPointF(cx + 10, cy + 14), "HOME (0, 0)")

        # Vẽ vệt di chuyển của UAV (Trail)
        if len(self.trail) > 1:
            trail_pen = QPen(QColor("#16a34a"), 2)
            painter.setPen(trail_pen)
            for i in range(len(self.trail) - 1):
                p1 = self._gps_to_screen(self.trail[i][0], self.trail[i][1])
                p2 = self._gps_to_screen(self.trail[i + 1][0], self.trail[i + 1][1])
                painter.drawLine(p1, p2)

        uav_pt = self._gps_to_screen(self.uav_lat, self.uav_lon)

        # Vẽ đường nối từ UAV tới Điểm đích (Target Waypoint)
        if self.waypoints:
            first_wp_pt = self._gps_to_screen(self.waypoints[0].latitude, self.waypoints[0].longitude)
            dash_pen = QPen(QColor("#38bdf8"), 2, Qt.PenStyle.DashLine)
            painter.setPen(dash_pen)
            painter.drawLine(uav_pt, first_wp_pt)

            for i in range(len(self.waypoints) - 1):
                p1 = self._gps_to_screen(self.waypoints[i].latitude, self.waypoints[i].longitude)
                p2 = self._gps_to_screen(self.waypoints[i + 1].latitude, self.waypoints[i + 1].longitude)
                painter.drawLine(p1, p2)

            for idx, wp in enumerate(self.waypoints):
                pt = self._gps_to_screen(wp.latitude, wp.longitude)
                wp_dx_cm, wp_dy_cm = gps_to_cm(wp.latitude, wp.longitude)
                dist_to_uav_cm = math.hypot(wp_dx_cm - uav_dx_cm, wp_dy_cm - uav_dy_cm)

                # Chỉ vẽ chấm Đích và chữ "Đích" khi UAV chưa tới nơi (cách đích > 1.5 cm)
                # để khi tới nơi không bị 2 hình đè lệch nhau gây hiểu lầm
                if dist_to_uav_cm > 1.5 or len(self.waypoints) > 1:
                    painter.setPen(QPen(QColor("#e0f2fe"), 2))
                    painter.setBrush(QBrush(QColor("#0284c7")))
                    painter.drawEllipse(pt, 5, 5)
                    painter.setPen(QColor("#38bdf8"))
                    label = (
                        f"Đích ({wp_dx_cm:+.0f}cm, {wp_dy_cm:+.0f}cm)"
                        if len(self.waypoints) == 1
                        else f"WP#{idx + 1}"
                    )
                    painter.drawText(QPointF(pt.x() + 9, pt.y() - 8), label)

        # Vẽ UAV: Chấm tròn đồng tâm đúng tại tọa độ uav_pt (không vẽ vạch thừa phía trước)
        uav_color = QColor("#eab308") if self.uav_mode == 2 else QColor("#22c55e")
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.setBrush(QBrush(uav_color))
        painter.drawEllipse(uav_pt, 7, 7)

        alt_cm = self.uav_alt * 100.0
        painter.setPen(uav_color)
        painter.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        painter.drawText(
            QPointF(uav_pt.x() + 12, uav_pt.y() + 5),
            f"UAV ({uav_dx_cm:+.0f}cm, {uav_dy_cm:+.0f}cm | Cao {alt_cm:.0f}cm)",
        )

        # Thanh thông tin ngắn gọn ở góc trên bên trái
        dist_cm = math.hypot(uav_dx_cm, uav_dy_cm)
        painter.setPen(QColor("#94a3b8"))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(
            12,
            20,
            f"Vị trí ước tính: Ngang (X) {uav_dx_cm:+.0f} cm | Dọc (Y) {uav_dy_cm:+.0f} cm "
            f"| Cách HOME: {dist_cm:.0f} cm",
        )
        painter.setPen(QColor("#64748b"))
        painter.drawText(
            12,
            38,
            "Mẹo: Bấm phím hướng bên trái HOẶC click chuột trực tiếp lên Radar để bay tới điểm đó.",
        )


class MapPanelWidget(QWidget):
    """Khung chứa Màn hình Radar Ước tính Vị trí UAV."""

    coordinate_selected = pyqtSignal(float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.canvas_map = TacticalCanvasMap()
        self.canvas_map.coordinate_clicked.connect(self.coordinate_selected.emit)
        layout.addWidget(self.canvas_map)

    def set_waypoints(self, waypoints: List[WaypointItem]) -> None:
        self.canvas_map.waypoints = list(waypoints)
        self.canvas_map.update()

    def update_uav_position(
        self,
        lat: float,
        lon: float,
        flight_mode: int = 0,
        alt: float = 0.0,
        yaw: float = 0.0,
    ) -> None:
        self.canvas_map.uav_lat = lat
        self.canvas_map.uav_lon = lon
        self.canvas_map.uav_mode = flight_mode
        self.canvas_map.uav_alt = alt
        self.canvas_map.uav_yaw = yaw
        if not self.canvas_map.trail or self.canvas_map.trail[-1] != (lat, lon):
            self.canvas_map.trail.append((lat, lon))
            if len(self.canvas_map.trail) > 400:
                self.canvas_map.trail.pop(0)
        self.canvas_map.update()

    def clear_trail(self) -> None:
        self.canvas_map.trail = [(self.canvas_map.uav_lat, self.canvas_map.uav_lon)]
        self.canvas_map.update()
