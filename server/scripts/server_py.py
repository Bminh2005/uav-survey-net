#!/usr/bin/env python3
"""
UAV Survey Net - Central Server (Python Runner)
Tích hợp:
1. TCP Server (Port 8080):
   - Nhận xác thực AUTH_REQ (0x01) -> trả lời AUTH_RES (0x02)
   - Nhận lệnh nạp tọa độ CMD_WAYPOINT (0x04)
   - Nhận lệnh điều khiển CMD_ACTION (0x05: Takeoff, Land, RTL)
2. UDP Telemetry Broadcaster (Port 8081 - 20Hz):
   - Tự động mô phỏng UAV bay theo các điểm Waypoint vừa nhận
   - Bắn luồng gói tin nhị phân TELEMETRY (0x03 - 34 bytes) về Client ở tần số 20Hz (50ms)
3. Web Client Interface:
   - Cung cấp giao diện Web trực quan tại http://localhost:8080
   - API /api/telemetry cho Web Browser
"""

import socket
import struct
import sys
import threading
import time
import math

TCP_PORT = 8080
UDP_PORT = 8081
MAGIC_WORD = 0xBEEF

HEADER_FORMAT = ">HBBI"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
WAYPOINT_FORMAT = ">4f"
WAYPOINT_SIZE = struct.calcsize(WAYPOINT_FORMAT)
MAX_WAYPOINTS = 50

OP_AUTH_REQ = 0x01
OP_AUTH_RES = 0x02
OP_TELEMETRY = 0x03
OP_CMD_WAYPOINT = 0x04
OP_CMD_ACTION = 0x05
OP_PING = 0x0A
OP_PONG = 0x0B

METERS_PER_DEG = 100000.0

def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Client ngắt kết nối.")
        buf.extend(chunk)
    return bytes(buf)

class ServerApp:
    def __init__(self, tcp_port=TCP_PORT, udp_port=UDP_PORT):
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        self.running = False

        self.lock = threading.Lock()
        self.uav_lat = 0.0
        self.uav_lon = 0.0
        self.uav_alt = 0.0
        self.uav_roll = 0.0
        self.uav_pitch = 0.0
        self.uav_yaw = 0.0
        self.uav_speed = 0.0
        self.uav_battery = 100.0
        self.uav_mode = 0 # 0: IDLE, 1: MISSION, 2: AUTO_RTL, 3: LANDED

        self.target_alt = 0.0
        self.active_waypoints = []
        self.connected_client_ip = "127.0.0.1"

    def start_udp_telemetry_loop(self):
        """Phát luồng UDP Telemetry 20Hz (mỗi 50ms) tới cổng 8081."""
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        dt = 0.05
        start_time = time.monotonic()
        packet_count = 0

        print(f"[UDP] Đã khởi tạo luồng bắn UDP Telemetry 20Hz tới cổng {self.udp_port}...")

        while self.running:
            time.sleep(dt)
            with self.lock:
                elapsed_ms = int((time.monotonic() - start_time) * 1000) & 0xFFFFFFFF

                # 1. Cập nhật Pin
                if self.uav_alt > 0.5 or self.uav_mode in (1, 2):
                    self.uav_battery = max(5.0, self.uav_battery - 0.02 * dt)

                # 2. Nội suy độ cao
                alt_diff = self.target_alt - self.uav_alt
                climb_step = 1.0 * dt
                if abs(alt_diff) <= climb_step:
                    self.uav_alt = self.target_alt
                else:
                    self.uav_alt += math.copysign(climb_step, alt_diff)

                if self.target_alt == 0.0 and self.uav_alt <= 0.02 and not self.active_waypoints:
                    self.uav_alt = 0.0
                    self.uav_speed = 0.0
                    self.uav_pitch = 0.0
                    self.uav_roll = 0.0
                    if self.uav_mode != 0:
                        self.uav_mode = 3 # LANDED

                # 3. Nội suy vị trí theo Waypoint
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
                            self.uav_pitch = 0.0
                            self.uav_roll = 0.0
                            if self.uav_mode == 2: # AUTO_RTL
                                self.target_alt = 0.0 # Hạ cánh khi về tới HOME
                    else:
                        heading = (math.degrees(math.atan2(dx_m, dy_m)) + 360.0) % 360.0
                        self.uav_yaw = heading
                        self.uav_speed = fly_speed
                        self.uav_pitch = -4.0
                        self.uav_roll = 1.2 * math.sin(time.monotonic() * 3.0)

                        self.uav_lon += (dx_m / dist_m * step_m) / METERS_PER_DEG
                        self.uav_lat += (dy_m / dist_m * step_m) / METERS_PER_DEG
                else:
                    self.uav_speed = abs(alt_diff) / dt if abs(alt_diff) > 0.01 else 0.0
                    self.uav_pitch = 0.0
                    self.uav_roll = 0.0

                # Đóng gói TelemetryPayload (34 bytes)
                telem_payload = struct.pack(
                    ">I7f2B",
                    elapsed_ms,
                    float(self.uav_lat),
                    float(self.uav_lon),
                    float(self.uav_alt),
                    float(self.uav_roll),
                    float(self.uav_pitch),
                    float(self.uav_yaw),
                    float(self.uav_speed),
                    int(round(self.uav_battery)) & 0xFF,
                    int(self.uav_mode) & 0xFF
                )

                lat_val = self.uav_lat
                lon_val = self.uav_lon
                alt_val = self.uav_alt
                spd_val = self.uav_speed
                bat_val = int(round(self.uav_battery))
                mode_val = self.uav_mode

            # Header 8 bytes (0xBEEF, msg_type=0x03)
            hdr = struct.pack(HEADER_FORMAT, MAGIC_WORD, OP_TELEMETRY, 0, len(telem_payload))
            pkt = hdr + telem_payload

            # Bắn gói tin UDP tới Client
            try:
                udp_sock.sendto(pkt, (self.connected_client_ip, self.udp_port))
                udp_sock.sendto(pkt, ("127.0.0.1", self.udp_port))
            except Exception:
                pass

            packet_count += 1
            if packet_count % 100 == 1:
                dx_cm = lon_val * METERS_PER_DEG * 100.0
                dy_cm = lat_val * METERS_PER_DEG * 100.0
                print(f"[UDP 20Hz #{packet_count:05d}] Pos:({lat_val:+.5f}, {lon_val:+.5f}) -> Radar:[X={dx_cm:+5.0f}cm, Y={dy_cm:+5.0f}cm] | Cao:{alt_val:4.1f}m | Tốc độ:{spd_val:3.1f}m/s | Pin:{bat_val}% | Mode:{mode_val}")

        udp_sock.close()

    def handle_client(self, sock: socket.socket, addr: tuple):
        print(f"\n[SERVER] Có kết nối TCP mới từ {addr[0]}:{addr[1]}")
        self.connected_client_ip = addr[0]

        try:
            while self.running:
                peek_data = sock.recv(4, socket.MSG_PEEK)
                if not peek_data:
                    break

                if peek_data in (b"GET ", b"POST"):
                    http_raw = sock.recv(2048).decode('utf-8', errors='ignore')
                    if "GET /api/telemetry" in http_raw:
                        with self.lock:
                            dx_cm = self.uav_lon * METERS_PER_DEG * 100.0
                            dy_cm = self.uav_lat * METERS_PER_DEG * 100.0
                            json_data = (
                                f'{{"lat":{self.uav_lat:.6f},"lon":{self.uav_lon:.6f},'
                                f'"alt":{self.uav_alt:.2f},"speed":{self.uav_speed:.2f},'
                                f'"yaw":{self.uav_yaw:.1f},"battery":{self.uav_battery:.0f},'
                                f'"mode":{self.uav_mode},"dx_cm":{dx_cm:.1f},"dy_cm":{dy_cm:.1f}}}'
                            )
                        resp = (
                            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                            "Access-Control-Allow-Origin: *\r\n"
                            f"Content-Length: {len(json_data)}\r\n\r\n{json_data}"
                        )
                        sock.sendall(resp.encode('utf-8'))
                    elif "POST /api/waypoint" in http_raw or "POST /coordinate" in http_raw:
                        body = http_raw.split("\r\n\r\n", 1)[-1]
                        import json
                        try:
                            d = json.loads(body)
                            lat = float(d.get('lat', 0.0))
                            lon = float(d.get('lon', 0.0))
                            alt = float(d.get('alt', 15.0))
                            spd = float(d.get('speed', 1.2))
                            with self.lock:
                                self.active_waypoints = [(lat, lon, alt, spd)]
                                self.uav_mode = 1 # MISSION
                                if self.uav_alt < 1.0:
                                    self.target_alt = alt
                            print(f"\n[WEB] Nhận tọa độ từ Web Client: Lat={lat:.6f}, Lon={lon:.6f}, Alt={alt}m")
                        except Exception:
                            pass
                        resp = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: 27\r\n\r\n{\"status\":\"ok\",\"code\":0}"
                        sock.sendall(resp.encode('utf-8'))
                    else:
                        try:
                            with open("uav-survey-net/server/web/web_client.html", "r", encoding="utf-8") as f:
                                html = f.read()
                        except Exception:
                            html = "<h1>UAV Server Ready</h1>"
                        resp = f"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {len(html.encode('utf-8'))}\r\n\r\n{html}"
                        sock.sendall(resp.encode('utf-8'))
                    break

                # Đọc Header 8 bytes nhị phân
                hdr_bytes = recv_exact(sock, HEADER_SIZE)
                magic, msg_type, status, plen = struct.unpack(HEADER_FORMAT, hdr_bytes)

                if magic != MAGIC_WORD:
                    print(f"[SERVER] Sai Magic: 0x{magic:04X}!")
                    break

                payload = recv_exact(sock, plen) if plen > 0 else b""

                if msg_type == OP_AUTH_REQ:
                    dev = payload[:16].decode('utf-8', errors='ignore').rstrip('\x00')
                    print(f"[SERVER] Nhận AUTH_REQ (0x01) từ '{dev}' -> Xác thực thành công!")
                    res_payload = struct.pack(">B32s", 0, b"TOK_UAV_SURVEY_2026_OK".ljust(32, b'\x00'))
                    res_hdr = struct.pack(HEADER_FORMAT, MAGIC_WORD, OP_AUTH_RES, 0, len(res_payload))
                    sock.sendall(res_hdr + res_payload)

                elif msg_type == OP_CMD_WAYPOINT:
                    count = struct.unpack(">H", payload[:2])[0]
                    print("\n" + "=" * 65)
                    print(f"  🎯 [SERVER] ĐÃ TIẾP NHẬN LỆNH GỬI TỌA ĐỘ (CMD_WAYPOINT 0x04)!")
                    print("=" * 65)
                    print(f" * Số lượng điểm: {count} điểm | Đang điều khiển UAV bay tới mục tiêu...")
                    print("-" * 65)

                    offset = 2
                    wps = []
                    for i in range(count):
                        lat, lon, alt, spd = struct.unpack(WAYPOINT_FORMAT, payload[offset:offset + WAYPOINT_SIZE])
                        wps.append((lat, lon, alt, spd))
                        dx_cm = lon * METERS_PER_DEG * 100.0
                        dy_cm = lat * METERS_PER_DEG * 100.0
                        print(f"  [Điểm {i+1:02d}] Lat: {lat:+10.6f} | Lon: {lon:+10.6f} | Cao: {alt:5.1f}m | Tốc độ: {spd:4.1f}m/s (Radar: X={dx_cm:+5.0f}cm, Y={dy_cm:+5.0f}cm)")
                        offset += WAYPOINT_SIZE
                    print("=" * 65 + "\n")

                    with self.lock:
                        self.active_waypoints = list(wps)
                        self.uav_mode = 1 # MISSION
                        if self.uav_alt < 1.0 and wps:
                            self.target_alt = max(1.0, wps[0][2])
                            print(f"[SERVER] UAV cất cánh lên độ cao {self.target_alt:.1f}m để bắt đầu hành trình!")

                    pong_hdr = struct.pack(HEADER_FORMAT, MAGIC_WORD, OP_PONG, 0, 0)
                    sock.sendall(pong_hdr)

                elif msg_type == OP_CMD_ACTION:
                    act = payload[0]
                    with self.lock:
                        if act == 1: # TAKEOFF
                            self.uav_mode = 1
                            self.target_alt = max(1.5, self.uav_alt)
                            print("[SERVER] Nhận lệnh TAKEOFF -> Cất cánh lên 1.5m!")
                        elif act == 2: # LAND
                            self.active_waypoints.clear()
                            self.target_alt = 0.0
                            print("[SERVER] Nhận lệnh LAND -> Đang hạ cánh khẩn cấp!")
                        elif act == 3: # RTL
                            self.uav_mode = 2 # AUTO_RTL
                            self.active_waypoints = [(0.0, 0.0, max(1.5, self.uav_alt), 1.0)]
                            print("[SERVER] Nhận lệnh RTL -> Quay về trạm gốc HOME (0, 0)!")

                elif msg_type == OP_PING:
                    pong_hdr = struct.pack(HEADER_FORMAT, MAGIC_WORD, OP_PONG, 0, 0)
                    sock.sendall(pong_hdr)

        except Exception:
            pass
        finally:
            sock.close()
            print(f"[SERVER] Client {addr[0]}:{addr[1]} đã đóng kết nối.")

    def run(self):
        self.running = True

        # Kích hoạt luồng UDP Telemetry 20Hz
        t_udp = threading.Thread(target=self.start_udp_telemetry_loop, daemon=True)
        t_udp.start()

        # Socket TCP lắng nghe
        tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp_sock.bind(("0.0.0.0", self.tcp_port))
        tcp_sock.listen(5)

        print("\n" + "=" * 65)
        print("  🚁 UAV SURVEY NET - CENTRAL SERVER (TCP & UDP 20Hz)")
        print("=" * 65)
        print(f" * Kênh TCP Nhận Lệnh:  Cổng {self.tcp_port} (CMD_WAYPOINT, CMD_ACTION)")
        print(f" * Kênh UDP Telemetry: Cổng {self.udp_port} (Bắn tọa độ 20Hz về Client)")
        print(f" * Web Client:          http://localhost:{self.tcp_port}")
        print("=" * 65 + "\n")

        try:
            while self.running:
                client_s, addr = tcp_sock.accept()
                t = threading.Thread(target=self.handle_client, args=(client_s, addr), daemon=True)
                t.start()
        except KeyboardInterrupt:
            print("\n[SERVER] Đang dừng máy chủ...")
        finally:
            self.running = False
            tcp_sock.close()

def main():
    tcp_port = int(sys.argv[1]) if len(sys.argv) > 1 else TCP_PORT
    udp_port = int(sys.argv[2]) if len(sys.argv) > 2 else UDP_PORT
    app = ServerApp(tcp_port, udp_port)
    app.run()

if __name__ == "__main__":
    main()
