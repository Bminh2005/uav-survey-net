#!/usr/bin/env python3
"""
Kịch bản kiểm thử toàn diện:
1. Client kết nối TCP tới Server (Port 8088), gửi xác thực AUTH_REQ (0x01).
2. Client gửi lệnh nạp tọa độ CMD_WAYPOINT (0x04 - 802 bytes).
3. Server bắt đầu điều khiển UAV bay tới các điểm tọa độ và BẮN GÓI TIN UDP TELEMETRY (0x03 - 20Hz)
   về Client trên cổng UDP 8081.
4. Client mở cổng UDP 8081 và đón nhận các gói tin Telemetry thời gian thực.
"""

import socket
import struct
import threading
import time
import math
import sys

SERVER_HOST = "127.0.0.1"
TCP_PORT = 8088
UDP_PORT = 8081
MAGIC_WORD = 0xBEEF

OP_AUTH_REQ = 0x01
OP_AUTH_RES = 0x02
OP_TELEMETRY = 0x03
OP_CMD_WAYPOINT = 0x04
OP_PING = 0x0A
OP_PONG = 0x0B

HEADER_FORMAT = ">HBBI"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
WAYPOINT_FORMAT = ">4f"
WAYPOINT_SIZE = struct.calcsize(WAYPOINT_FORMAT)
MAX_WAYPOINTS = 50

C_RESET = "\033[0m"
C_GREEN = "\033[1;32m"
C_CYAN = "\033[1;36m"
C_YELLOW = "\033[1;33m"
C_RED = "\033[1;31m"
C_MAGENTA = "\033[1;35m"

METERS_PER_DEG = 100000.0

def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Kết nối đóng.")
        buf.extend(chunk)
    return bytes(buf)

# ======================================================================
# PHẦN SERVER: Nhận TCP & Bắn UDP Telemetry 20Hz
# ======================================================================
class DemoServer:
    def __init__(self, tcp_port=TCP_PORT, udp_port=UDP_PORT):
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        self.running = False
        self.tcp_sock = None
        self.udp_sock = None

        self.lock = threading.Lock()
        self.uav_lat = 0.0
        self.uav_lon = 0.0
        self.uav_alt = 0.0
        self.uav_speed = 0.0
        self.uav_yaw = 0.0
        self.uav_battery = 100.0
        self.uav_mode = 0 # IDLE
        self.active_waypoints = []
        self.target_alt = 0.0

    def start(self):
        self.running = True
        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_sock.bind((SERVER_HOST, self.tcp_port))
        self.tcp_sock.listen(5)

        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        print(f"{C_CYAN}[SERVER]{C_RESET} Khởi động TCP Socket (Port {self.tcp_port}) & Kênh UDP Telemetry (Port {self.udp_port})")

        threading.Thread(target=self._tcp_listen_loop, daemon=True).start()
        threading.Thread(target=self._udp_telemetry_loop, daemon=True).start()

    def _udp_telemetry_loop(self):
        dt = 0.05
        start_t = time.monotonic()
        count = 0

        while self.running:
            time.sleep(dt)
            with self.lock:
                elapsed_ms = int((time.monotonic() - start_t) * 1000) & 0xFFFFFFFF

                # Cập nhật độ cao
                alt_diff = self.target_alt - self.uav_alt
                climb = 1.0 * dt
                if abs(alt_diff) <= climb:
                    self.uav_alt = self.target_alt
                else:
                    self.uav_alt += math.copysign(climb, alt_diff)

                # Di chuyển theo Waypoint
                if self.active_waypoints:
                    wp_lat, wp_lon, wp_alt, wp_spd = self.active_waypoints[0]
                    self.target_alt = wp_alt

                    dx_m = (wp_lon - self.uav_lon) * METERS_PER_DEG
                    dy_m = (wp_lat - self.uav_lat) * METERS_PER_DEG
                    dist_m = math.hypot(dx_m, dy_m)

                    fly_speed = max(0.5, wp_spd)
                    step_m = fly_speed * dt

                    if dist_m <= step_m or dist_m < 0.01:
                        self.uav_lat = wp_lat
                        self.uav_lon = wp_lon
                        self.active_waypoints.pop(0)
                        if not self.active_waypoints:
                            self.uav_speed = 0.0
                    else:
                        heading = (math.degrees(math.atan2(dx_m, dy_m)) + 360.0) % 360.0
                        self.uav_yaw = heading
                        self.uav_speed = fly_speed
                        self.uav_lon += (dx_m / dist_m * step_m) / METERS_PER_DEG
                        self.uav_lat += (dy_m / dist_m * step_m) / METERS_PER_DEG

                telem = struct.pack(
                    ">I7f2B",
                    elapsed_ms,
                    float(self.uav_lat), float(self.uav_lon), float(self.uav_alt),
                    0.0, -3.0, float(self.uav_yaw), float(self.uav_speed),
                    int(round(self.uav_battery)) & 0xFF, int(self.uav_mode) & 0xFF
                )

            hdr = struct.pack(HEADER_FORMAT, MAGIC_WORD, OP_TELEMETRY, 0, len(telem))
            pkt = hdr + telem

            # Bắn gói tin UDP về Client tại cổng 8081
            try:
                self.udp_sock.sendto(pkt, (SERVER_HOST, self.udp_port))
            except Exception:
                pass

            count += 1
            if count % 20 == 1: # In mỗi 1 giây một lần
                dx_cm = self.uav_lon * METERS_PER_DEG * 100.0
                dy_cm = self.uav_lat * METERS_PER_DEG * 100.0
                print(f"{C_CYAN}[SERVER -> UDP 20Hz]{C_RESET} Bắn gói tin: Pos=({self.uav_lat:+.5f}, {self.uav_lon:+.5f}) [X={dx_cm:+4.0f}cm, Y={dy_cm:+4.0f}cm] | Cao={self.uav_alt:4.1f}m | Tốc độ={self.uav_speed:3.1f}m/s")

    def _tcp_listen_loop(self):
        while self.running:
            try:
                c, a = self.tcp_sock.accept()
                threading.Thread(target=self._handle_client, args=(c, a), daemon=True).start()
            except Exception:
                break

    def _handle_client(self, sock: socket.socket, addr: tuple):
        try:
            while self.running:
                hdr_bytes = recv_exact(sock, HEADER_SIZE)
                magic, msg_type, status, plen = struct.unpack(HEADER_FORMAT, hdr_bytes)
                payload = recv_exact(sock, plen) if plen > 0 else b""

                if msg_type == OP_AUTH_REQ:
                    res_payload = struct.pack(">B32s", 0, b"TOK_DEMO_2026_OK".ljust(32, b'\x00'))
                    res_hdr = struct.pack(HEADER_FORMAT, MAGIC_WORD, OP_AUTH_RES, 0, len(res_payload))
                    sock.sendall(res_hdr + res_payload)

                elif msg_type == OP_CMD_WAYPOINT:
                    count = struct.unpack(">H", payload[:2])[0]
                    print(f"\n{C_GREEN}>>> [SERVER] ĐÃ NHẬN ĐƯỢC LỆNH GỬI TỌA ĐỘ (CMD_WAYPOINT) GỒM {count} ĐIỂM!{C_RESET}")
                    offset = 2
                    wps = []
                    for i in range(count):
                        lat, lon, alt, spd = struct.unpack(WAYPOINT_FORMAT, payload[offset:offset + WAYPOINT_SIZE])
                        wps.append((lat, lon, alt, spd))
                        offset += WAYPOINT_SIZE

                    with self.lock:
                        self.active_waypoints = list(wps)
                        self.uav_mode = 1 # MISSION
                        if self.uav_alt < 1.0 and wps:
                            self.target_alt = wps[0][2]
                            print(f"{C_YELLOW}[SERVER] UAV bắt đầu cất cánh lên {self.target_alt}m và bay tới mục tiêu!{C_RESET}\n")

                    pong_hdr = struct.pack(HEADER_FORMAT, MAGIC_WORD, OP_PONG, 0, 0)
                    sock.sendall(pong_hdr)

        except Exception:
            pass
        finally:
            sock.close()

    def stop(self):
        self.running = False
        if self.tcp_sock: self.tcp_sock.close()
        if self.udp_sock: self.udp_sock.close()

# ======================================================================
# PHẦN CLIENT: Gửi TCP & Nhận UDP Telemetry 20Hz
# ======================================================================
def run_client():
    time.sleep(0.5)

    # 1. Luồng Client nhận UDP Telemetry tại Port 8081
    udp_rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp_rx.bind((SERVER_HOST, UDP_PORT))

    def udp_listener():
        print(f"{C_YELLOW}[CLIENT UDP]{C_RESET} Đang mở cổng {UDP_PORT} đón luồng Telemetry 20Hz...")
        received = 0
        while received < 10:
            data, _ = udp_rx.recvfrom(1024)
            if len(data) >= HEADER_SIZE + 34:
                magic, msg_type, status, plen = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
                if msg_type == OP_TELEMETRY:
                    telem = data[HEADER_SIZE : HEADER_SIZE + 34]
                    ts, lat, lon, alt, r, p, yaw, spd, bat, mode = struct.unpack(">I7f2B", telem)
                    dx_cm = lon * METERS_PER_DEG * 100.0
                    dy_cm = lat * METERS_PER_DEG * 100.0
                    print(f"{C_GREEN}[CLIENT NHẬN TELEMETRY UDP]{C_RESET} #{received+1:02d} | Tọa độ: ({lat:+.6f}, {lon:+.6f}) -> Radar:[X={dx_cm:+4.0f}cm, Y={dy_cm:+4.0f}cm] | Cao={alt:4.1f}m | Tốc độ={spd:3.1f}m/s | Pin={bat}%")
                    received += 1
        udp_rx.close()

    t_listener = threading.Thread(target=udp_listener, daemon=True)
    t_listener.start()

    # 2. Client gửi TCP
    print(f"\n{C_YELLOW}[CLIENT TCP]{C_RESET} Kết nối tới Server {SERVER_HOST}:{TCP_PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((SERVER_HOST, TCP_PORT))

    # Gửi AUTH_REQ
    auth_data = "CLIENT_WEB_01".encode().ljust(16, b'\x00') + "SecretKey2026".encode().ljust(32, b'\x00')
    sock.sendall(struct.pack(HEADER_FORMAT, MAGIC_WORD, OP_AUTH_REQ, 0, len(auth_data)) + auth_data)
    sock.recv(HEADER_SIZE + 33) # Đọc AUTH_RES

    # Gửi lệnh nạp tọa độ CMD_WAYPOINT (0x04)
    # Gửi điểm đích: X = +150cm (0.000015 deg), Y = +200cm (0.000020 deg), Cao 12m
    target_wps = [(0.000020, 0.000015, 12.0, 1.5)]
    buf = bytearray(struct.pack(">H", len(target_wps)))
    for lat, lon, alt, spd in target_wps:
        buf.extend(struct.pack(WAYPOINT_FORMAT, lat, lon, alt, spd))
    buf.extend(b"\x00" * ((MAX_WAYPOINTS - len(target_wps)) * WAYPOINT_SIZE))

    print(f"{C_YELLOW}[CLIENT TCP]{C_RESET} Gửi lệnh CMD_WAYPOINT (0x04) nạp tọa độ đích: X=+150cm, Y=+200cm, Cao=12m...")
    sock.sendall(struct.pack(HEADER_FORMAT, MAGIC_WORD, OP_CMD_WAYPOINT, 0, len(buf)) + bytes(buf))

    sock.recv(HEADER_SIZE) # Đọc PONG

    # Chờ nhận đủ 10 gói UDP
    t_listener.join(timeout=5.0)
    sock.close()

# ======================================================================
# CHƯƠNG TRÌNH CHÍNH
# ======================================================================
def main():
    print("=" * 75)
    print("   KIỂM THỬ: GỬI LỆNH TỌA ĐỘ QUA TCP & BẮN GÓI TIN UDP TELEMETRY VỀ CLIENT")
    print("=" * 75 + "\n")

    server = DemoServer()
    server.start()

    run_client()

    time.sleep(1.0)
    server.stop()
    print("\n" + "=" * 75)
    print("   THỬ NGHIỆM THÀNH CÔNG: SERVER ĐÃ BẮN LUỒNG UDP TELEMETRY VỀ CLIENT!")
    print("=" * 75)

if __name__ == "__main__":
    main()
