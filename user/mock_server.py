"""
Giả lập Máy chủ Trung tâm & Thiết bị bay (Mock Central Server + UAV Flight Simulator).
Hỗ trợ:
1. Kênh TCP (Port 8080):
   - Xác thực `AUTH_REQ` (0x01) -> trả về `AUTH_RES` (0x02).
   - Nhận gói `CMD_WAYPOINT` (0x04): Đặt mục tiêu bay cho UAV nội suy tọa độ di chuyển tới đích.
   - Nhận gói `CMD_ACTION` (0x05):
       + `1 (TAKEOFF)`: Cất cánh nâng độ cao lên 20m.
       + `2 (LAND)`: Hạ cánh từ từ xuống 0m (`flight_mode = LANDED`).
       + `3 (RTL)`: Kích hoạt `flight_mode = 2 (AUTO_RTL)`, tự động bay về Trạm gốc HOME rồi hạ cánh.
   - Gửi nhịp tim `PING` (0x0A) mỗi 2 giây và nhận `PONG` (0x0B).
2. Kênh UDP (Port 8081 - 20Hz):
   - Mô phỏng chuyển động vật lý (nội suy tọa độ Lat/Lon/Alt, góc hướng Yaw, góc nghiêng Pitch/Roll,
     vận tốc Speed, dung lượng Pin) chu kỳ 50ms (20Hz) và bắn gói `TELEMETRY` (0x03) về Client.

Chạy độc lập:
    python mock_server.py
"""

from __future__ import annotations

import argparse
import math
import select
import socket
import sys
import threading
import time
from typing import List, Optional

from protocol import (
    ActionType,
    AuthReqPayload,
    AuthResPayload,
    CmdActionPayload,
    CmdWaypointPayload,
    FlightMode,
    OpCode,
    TelemetryPayload,
    WaypointItem,
    pack_message,
    recv_tcp_message,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HOME_LAT = 0.0
HOME_LON = 0.0
METERS_PER_DEG_LAT = 100_000.0
METERS_PER_DEG_LON = 100_000.0


class MockCentralServer:
    """Mock Central Server tích hợp bộ giả lập bay 20Hz phát UDP Telemetry (0x03)."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        tcp_port: int = 8080,
        udp_port: int = 8081,
        valid_secret: Optional[str] = None,
        session_token: str = "TOK_UAV_SURVEY_2026_OK",
        ping_interval: float = 2.0,
        enable_udp_telemetry: bool = True,
    ) -> None:
        self.host = host
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        self.valid_secret = valid_secret
        self.session_token = session_token
        self.ping_interval = ping_interval
        self.enable_udp_telemetry = enable_udp_telemetry

        self._server_sock: Optional[socket.socket] = None
        self._udp_sock: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._sim_thread: Optional[threading.Thread] = None

        # Trạng thái mô phỏng vật lý của UAV
        self.lock = threading.Lock()
        self.uav_lat: float = HOME_LAT
        self.uav_lon: float = HOME_LON
        self.uav_alt: float = 0.0
        self.uav_roll: float = 0.0
        self.uav_pitch: float = 0.0
        self.uav_yaw: float = 0.0
        self.uav_speed: float = 0.0
        self.uav_battery: float = 100.0
        self.uav_mode: int = int(FlightMode.IDLE)

        self.target_alt: float = 0.0
        self.active_waypoints: List[WaypointItem] = []
        self._start_time = time.monotonic()

        # Lưu lịch sử gói tin nhận được để kiểm thử tự động
        self.authenticated_devices: List[str] = []
        self.received_waypoints: List[List[WaypointItem]] = []
        self.received_actions: List[int] = []
        self.pong_count: int = 0

    def start(self) -> int:
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.host, self.tcp_port))
        self._server_sock.listen(5)
        self.tcp_port = self._server_sock.getsockname()[1]

        self._udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

        if self.enable_udp_telemetry:
            self._sim_thread = threading.Thread(target=self._simulation_loop_20hz, daemon=True)
            self._sim_thread.start()

        print(
            f"[MockServer] Đang lắng nghe TCP tại {self.host}:{self.tcp_port} | "
            f"Phát UDP Telemetry 20Hz tới cổng {self.udp_port} (Magic=0xBEEF)..."
        )
        return self.tcp_port

    def stop(self) -> None:
        self._running = False
        if self._server_sock is not None:
            try:
                self._server_sock.close()
            except OSError:
                pass
            self._server_sock = None
        if self._udp_sock is not None:
            try:
                self._udp_sock.close()
            except OSError:
                pass
            self._udp_sock = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._sim_thread is not None:
            self._sim_thread.join(timeout=2.0)
            self._sim_thread = None

    # ------------------------------------------------------------------
    # Vòng lặp mô phỏng chuyển động UAV & Phát UDP Telemetry 20Hz (50ms)
    # ------------------------------------------------------------------
    def _simulation_loop_20hz(self) -> None:
        dt = 0.05  # 50ms = 20Hz
        while self._running:
            time.sleep(dt)
            with self.lock:
                self._step_physics(dt)
                elapsed_ms = int((time.monotonic() - self._start_time) * 1000) & 0xFFFFFFFF
                telem = TelemetryPayload(
                    timestamp_ms=elapsed_ms,
                    latitude=self.uav_lat,
                    longitude=self.uav_lon,
                    altitude=self.uav_alt,
                    roll=self.uav_roll,
                    pitch=self.uav_pitch,
                    yaw=self.uav_yaw,
                    speed=self.uav_speed,
                    battery=int(round(self.uav_battery)),
                    flight_mode=self.uav_mode,
                )

            if self._udp_sock is not None:
                pkt = pack_message(OpCode.TELEMETRY, telem.pack(), status=0)
                try:
                    self._udp_sock.sendto(pkt, (self.host, self.udp_port))
                except OSError:
                    pass

    def _step_physics(self, dt: float) -> None:
        """Nội suy tọa độ bay mượt mà ở tần số 20Hz."""
        # Hao pin nhẹ khi đang bay
        if self.uav_alt > 0.5 or self.uav_mode in (FlightMode.MISSION, FlightMode.AUTO_RTL):
            self.uav_battery = max(5.0, self.uav_battery - 0.03 * dt)

        # 1. Nội suy độ cao (Altitude) tiến về target_alt
        alt_diff = self.target_alt - self.uav_alt
        max_climb_step = 0.8 * dt  # Tốc độ nâng/hạ 80 cm/s (0.8 m/s) phù hợp bay trong phòng/sân nhỏ
        if abs(alt_diff) <= max_climb_step:
            self.uav_alt = self.target_alt
        else:
            self.uav_alt += math.copysign(max_climb_step, alt_diff)

        # Nếu đang hạ cánh (target_alt == 0) và đã chạm đất
        if self.target_alt == 0.0 and self.uav_alt <= 0.02 and not self.active_waypoints:
            self.uav_alt = 0.0
            self.uav_speed = 0.0
            self.uav_pitch = 0.0
            self.uav_roll = 0.0
            if self.uav_mode != FlightMode.IDLE:
                self.uav_mode = int(FlightMode.LANDED)
            return

        # 2. Nội suy vị trí ngang (Lat, Lon) tiến về điểm Waypoint đầu hàng đợi
        if self.active_waypoints:
            wp = self.active_waypoints[0]
            self.target_alt = wp.altitude
            dx_east = (wp.longitude - self.uav_lon) * METERS_PER_DEG_LON
            dy_north = (wp.latitude - self.uav_lat) * METERS_PER_DEG_LAT
            dist_m = math.hypot(dx_east, dy_north)

            fly_speed = max(0.3, wp.speed)  # Mặc định ~0.8 m/s (80 cm/s)
            step_m = fly_speed * dt

            if dist_m <= step_m or dist_m < 0.01:
                # Đã tới điểm Waypoint này (sai số < 1cm)
                self.uav_lat = wp.latitude
                self.uav_lon = wp.longitude
                self.active_waypoints.pop(0)
                if not self.active_waypoints:
                    self.uav_speed = 0.0
                    self.uav_pitch = 0.0
                    self.uav_roll = 0.0
                    if self.uav_mode == FlightMode.AUTO_RTL:
                        self.target_alt = 0.0
            else:
                heading_deg = (math.degrees(math.atan2(dx_east, dy_north)) + 360.0) % 360.0
                self.uav_yaw = heading_deg
                self.uav_speed = fly_speed
                self.uav_pitch = -4.0
                self.uav_roll = 1.5 * math.sin(time.monotonic() * 2.0)

                ux = dx_east / dist_m
                uy = dy_north / dist_m
                self.uav_lon += (ux * step_m) / METERS_PER_DEG_LON
                self.uav_lat += (uy * step_m) / METERS_PER_DEG_LAT
        else:
            self.uav_speed = abs(alt_diff) / dt if abs(alt_diff) > 0.01 else 0.0
            self.uav_pitch = 0.0
            self.uav_roll = 0.0

    # ------------------------------------------------------------------
    # Xử lý kết nối & Lệnh TCP (Port 8080)
    # ------------------------------------------------------------------
    def _accept_loop(self) -> None:
        while self._running and self._server_sock is not None:
            try:
                readable, _, _ = select.select([self._server_sock], [], [], 0.2)
                if not readable:
                    continue
                client_sock, addr = self._server_sock.accept()
                client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_sock, addr),
                    daemon=True,
                )
                client_thread.start()
            except OSError:
                break

    def _check_secret(self, secret_key: str) -> bool:
        if not secret_key or secret_key == "wrong":
            return False
        if self.valid_secret is not None:
            return secret_key == self.valid_secret
        return True

    def _handle_client(self, client_sock: socket.socket, addr: tuple) -> None:
        print(f"[MockServer] Kết nối TCP mới từ {addr}")
        is_authed = False
        last_ping = time.monotonic()

        try:
            while self._running:
                readable, _, _ = select.select([client_sock], [], [], 0.1)

                now = time.monotonic()
                if is_authed and self.ping_interval > 0 and (now - last_ping) >= self.ping_interval:
                    ping_pkt = pack_message(OpCode.PING, b"", status=0)
                    client_sock.sendall(ping_pkt)
                    last_ping = now

                if not readable:
                    continue

                header, payload = recv_tcp_message(client_sock)

                if header.msg_type == OpCode.AUTH_REQ:
                    req = AuthReqPayload.unpack(payload)
                    print(
                        f"[MockServer] Nhận AUTH_REQ (0x01): device_id='{req.device_id}', "
                        f"secret_key='{req.secret_key}'"
                    )
                    if self._check_secret(req.secret_key):
                        is_authed = True
                        with self.lock:
                            self.authenticated_devices.append(req.device_id)
                        res = AuthResPayload(status_code=0, session_token=self.session_token)
                        pkt = pack_message(OpCode.AUTH_RES, res.pack(), status=0)
                        client_sock.sendall(pkt)
                        print(f"[MockServer] -> Xác thực THÀNH CÔNG cho '{req.device_id}'")
                    else:
                        res = AuthResPayload(status_code=1, session_token="")
                        pkt = pack_message(OpCode.AUTH_RES, res.pack(), status=1)
                        client_sock.sendall(pkt)
                        print(f"[MockServer] -> Xác thực THẤT BẠI cho '{req.device_id}' (Sai secret_key)")
                        break

                elif header.msg_type == OpCode.CMD_WAYPOINT:
                    if not is_authed:
                        continue
                    wp_cmd = CmdWaypointPayload.unpack(payload)
                    with self.lock:
                        self.received_waypoints.append(wp_cmd.waypoints)
                        self.active_waypoints = list(wp_cmd.waypoints)
                        self.uav_mode = int(FlightMode.MISSION)
                        if self.uav_alt < 2.0 and wp_cmd.waypoints:
                            self.target_alt = wp_cmd.waypoints[0].altitude

                    print(
                        f"[MockServer] Nhận CMD_WAYPOINT (0x04) | Số điểm: {len(wp_cmd.waypoints)} "
                        f"-> UAV bắt đầu bay tới đích!"
                    )
                    for i, wp in enumerate(wp_cmd.waypoints, start=1):
                        print(
                            f"   WP#{i:02d}: Lat={wp.latitude:.6f}, Lon={wp.longitude:.6f}, "
                            f"Alt={wp.altitude:.1f}m, Speed={wp.speed:.1f}m/s"
                        )

                elif header.msg_type == OpCode.CMD_ACTION:
                    if not is_authed:
                        continue
                    act_cmd = CmdActionPayload.unpack(payload)
                    with self.lock:
                        self.received_actions.append(act_cmd.action_type)
                        if act_cmd.action_type == ActionType.TAKEOFF:
                            self.uav_mode = int(FlightMode.MISSION)
                            self.target_alt = max(1.0, self.target_alt)
                            print("[MockServer] Nhận CMD_ACTION: TAKEOFF (1) -> Đang cất cánh lên 100 cm (1.0m)!")
                        elif act_cmd.action_type == ActionType.LAND:
                            self.active_waypoints.clear()
                            self.target_alt = 0.0
                            print("[MockServer] Nhận CMD_ACTION: LAND (2) -> Đang hạ cánh tại chỗ!")
                        elif act_cmd.action_type == ActionType.RTL:
                            self.uav_mode = int(FlightMode.AUTO_RTL)
                            self.target_alt = max(1.2, self.uav_alt)
                            self.active_waypoints = [
                                WaypointItem(
                                    latitude=HOME_LAT,
                                    longitude=HOME_LON,
                                    altitude=self.target_alt,
                                    speed=0.8,
                                )
                            ]
                            print(
                                "[MockServer] Nhận CMD_ACTION: RTL (3) -> Kích hoạt SAFE RTL bay về HOME!"
                            )

                elif header.msg_type == OpCode.PONG:
                    with self.lock:
                        self.pong_count += 1

        except ConnectionError:
            print(f"[MockServer] Client {addr} đã đóng kết nối (recv() == 0).")
        except Exception as exc:
            print(f"[MockServer] Lỗi xử lý Client {addr}: {exc}")
        finally:
            try:
                client_sock.close()
            except OSError:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock Central Server & UAV Simulator (Đề tài 11)")
    parser.add_argument("--host", default="127.0.0.1", help="Địa chỉ IP (mặc định: 127.0.0.1)")
    parser.add_argument("--tcp-port", type=int, default=8080, help="Cổng TCP (mặc định: 8080)")
    parser.add_argument("--udp-port", type=int, default=8081, help="Cổng UDP Telemetry (mặc định: 8081)")
    args = parser.parse_args()

    server = MockCentralServer(host=args.host, tcp_port=args.tcp_port, udp_port=args.udp_port)
    server.start()
    print("[MockServer] Đang mô phỏng bay 20Hz. Nhấn Ctrl+C để dừng Server.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[MockServer] Đang dừng...")
        server.stop()


if __name__ == "__main__":
    main()
