"""
Worker Threads xử lý kết nối mạng TCP (Port 8080) và UDP (Port 8081) cho Ứng dụng GCS Client (Thành viên 3).
Đảm bảo toàn bộ thao tác Socket chạy trên luồng phụ (QThread), không gây đóng băng UI (UI Freeze).
"""

from __future__ import annotations

import queue
import select
import socket
import time
from typing import List, Optional

from PyQt6.QtCore import QThread, pyqtSignal

from protocol import (
    HEADER_SIZE,
    ActionType,
    AuthReqPayload,
    AuthResPayload,
    CmdActionPayload,
    CmdWaypointPayload,
    MessageHeader,
    OpCode,
    TelemetryPayload,
    WaypointItem,
    pack_message,
    recv_tcp_message,
)


class TcpClientWorker(QThread):
    """
    Luồng phụ quản lý kết nối TCP tới Central Server (Port 8080):
    - Thực hiện xác thực AUTH_REQ (0x01) -> nhận AUTH_RES (0x02).
    - Gửi lệnh hành trình CMD_WAYPOINT (0x04) từ hàng đợi bất đồng bộ.
    - Gửi lệnh can thiệp tức thời CMD_ACTION (0x05: Takeoff, Land, RTL).
    - Tự động phản hồi PONG (0x0B) nếu nhận gói PING (0x0A) từ Server.
    """

    auth_result = pyqtSignal(bool, str, str)     # (success, message, session_token)
    connection_closed = pyqtSignal(str)          # (reason)
    command_sent = pyqtSignal(str)               # (log_message)
    log_message = pyqtSignal(str)                # (general_log)

    def __init__(
        self,
        server_ip: str,
        tcp_port: int,
        device_id: str,
        secret_key: str,
        connect_timeout: float = 5.0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.server_ip = server_ip.strip()
        self.tcp_port = int(tcp_port)
        self.device_id = device_id.strip()
        self.secret_key = secret_key
        self.connect_timeout = connect_timeout

        self._sock: Optional[socket.socket] = None
        self._running: bool = False
        self._send_queue: "queue.Queue[tuple[bytes, str]]" = queue.Queue()

    def send_waypoints(self, waypoints: List[WaypointItem]) -> None:
        """Đóng gói CMD_WAYPOINT (0x04) và đưa vào hàng đợi gửi TCP."""
        payload = CmdWaypointPayload(waypoints=waypoints).pack()
        packet = pack_message(OpCode.CMD_WAYPOINT, payload, status=0)
        if len(waypoints) == 1:
            wp = waypoints[0]
            desc = (
                f"[TX -> TCP] CMD_WAYPOINT (0x04) | Bay tới đích: "
                f"({wp.latitude:.6f}, {wp.longitude:.6f}, Cao={wp.altitude * 100:.0f}cm)"
            )
        else:
            desc = f"[TX -> TCP] CMD_WAYPOINT (0x04) | Số điểm: {len(waypoints)}"
        self._send_queue.put((packet, desc))

    def send_action(self, action_type: int) -> None:
        """Đóng gói CMD_ACTION (0x05) và đưa vào hàng đợi gửi TCP."""
        action_enum = ActionType(action_type)
        payload = CmdActionPayload(action_type=int(action_enum)).pack()
        packet = pack_message(OpCode.CMD_ACTION, payload, status=0)
        desc = f"[TX -> TCP] CMD_ACTION (0x05) | Lệnh: {action_enum.name} ({int(action_enum)})"
        self._send_queue.put((packet, desc))

    def stop_worker(self) -> None:
        self._running = False
        sock = self._sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def run(self) -> None:
        self._running = True
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.connect_timeout)
        self._sock = sock

        try:
            self.log_message.emit(
                f"Đang kết nối TCP tới {self.server_ip}:{self.tcp_port} (ID='{self.device_id}')..."
            )
            sock.connect((self.server_ip, self.tcp_port))

            # 1. Gửi AUTH_REQ (0x01)
            auth_req = AuthReqPayload(device_id=self.device_id, secret_key=self.secret_key)
            req_bytes = auth_req.pack()
            req_packet = pack_message(OpCode.AUTH_REQ, req_bytes, status=0)
            sock.sendall(req_packet)

            # 2. Đọc AUTH_RES (0x02)
            header, payload_bytes = recv_tcp_message(sock)
            if header.msg_type != OpCode.AUTH_RES:
                msg = f"Phản hồi không phải AUTH_RES (msg_type=0x{header.msg_type:02X})"
                self.auth_result.emit(False, msg, "")
                return

            auth_res = AuthResPayload.unpack(payload_bytes)
            if header.status != 0 or auth_res.status_code != 0:
                err_code = header.status if header.status != 0 else auth_res.status_code
                msg = f"Xác thực thất bại (Mã lỗi: {err_code})"
                self.auth_result.emit(False, msg, "")
                return

            self.auth_result.emit(
                True,
                f"Đã kết nối ({self.server_ip}:{self.tcp_port})",
                auth_res.session_token,
            )

            sock.settimeout(None)
            while self._running:
                while not self._send_queue.empty():
                    packet, desc = self._send_queue.get_nowait()
                    sock.sendall(packet)
                    self.command_sent.emit(desc)

                readable, _, exceptional = select.select([sock], [], [sock], 0.05)
                if exceptional:
                    raise ConnectionError("Lỗi ngoại lệ trên kênh TCP")

                if readable:
                    rx_header, _ = recv_tcp_message(sock)
                    if rx_header.msg_type == OpCode.PING:
                        pong_packet = pack_message(OpCode.PONG, b"", status=0)
                        sock.sendall(pong_packet)

        except Exception as exc:
            if self._running:
                self.connection_closed.emit(str(exc))
            else:
                self.connection_closed.emit("Đã ngắt kết nối.")
        finally:
            self._running = False
            try:
                sock.close()
            except OSError:
                pass
            self._sock = None


class UdpTelemetryWorker(QThread):
    """
    Luồng phụ lắng nghe gói tin UDP TELEMETRY (0x03 - 20Hz) trên cổng 8081:
    - Giải mã Header 8B (`0xBEEF`) + `TelemetryPayload` (34B).
    - Đẩy dữ liệu thời gian thực lên UI qua Signal `telemetry_received`.
    - Phát hiện mất tín hiệu nếu quá 3 giây không nhận được gói UDP nào (`telemetry_timeout`).
    """

    telemetry_received = pyqtSignal(object)      # TelemetryPayload
    telemetry_timeout = pyqtSignal(bool)         # True khi mất sóng > 3s, False khi có lại
    log_message = pyqtSignal(str)

    def __init__(self, udp_port: int = 8081, timeout_sec: float = 3.0, parent=None) -> None:
        super().__init__(parent)
        self.udp_port = int(udp_port)
        self.timeout_sec = timeout_sec
        self._running = False
        self._sock: Optional[socket.socket] = None

    def stop_worker(self) -> None:
        self._running = False
        sock = self._sock
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def run(self) -> None:
        self._running = True
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock = sock

        try:
            sock.bind(("0.0.0.0", self.udp_port))
            self.log_message.emit(f"[UDP] Đang lắng nghe Telemetry 20Hz tại cổng {self.udp_port}...")
        except OSError as exc:
            self.log_message.emit(f"[UDP Lỗi] Không thể mở cổng UDP {self.udp_port}: {exc}")
            return

        last_rx_time = time.monotonic()
        is_timed_out = False

        try:
            while self._running:
                readable, _, _ = select.select([sock], [], [], 0.1)
                now = time.monotonic()

                if not readable:
                    if not is_timed_out and (now - last_rx_time) >= self.timeout_sec:
                        is_timed_out = True
                        self.telemetry_timeout.emit(True)
                    continue

                data, _ = sock.recvfrom(2048)
                if len(data) < HEADER_SIZE:
                    continue

                try:
                    header = MessageHeader.unpack(data[:HEADER_SIZE])
                    if header.msg_type != OpCode.TELEMETRY:
                        continue
                    payload_bytes = data[HEADER_SIZE : HEADER_SIZE + header.payload_len]
                    telemetry = TelemetryPayload.unpack(payload_bytes)
                except ValueError:
                    continue

                last_rx_time = now
                if is_timed_out:
                    is_timed_out = False
                    self.telemetry_timeout.emit(False)

                self.telemetry_received.emit(telemetry)
        except OSError:
            pass
        finally:
            self._running = False
            try:
                sock.close()
            except OSError:
                pass
            self._sock = None
