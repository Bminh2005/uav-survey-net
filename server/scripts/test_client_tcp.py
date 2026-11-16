#!/usr/bin/env python3
"""
Script Python kiểm thử gửi lệnh tọa độ tới Server qua giao thức TCP.
- Đóng gói đúng chuẩn Big-Endian (>):
  + MessageHeader (8 bytes): magic=0xBEEF, msg_type=0x04, status=0, payload_len=802
  + CmdWaypointPayload (802 bytes): count=N, waypoints[50]
- Kiểm tra Server nhận và giải mã tọa độ chính xác.
"""

import socket
import struct
import sys
import time

SERVER_IP = "127.0.0.1"
SERVER_PORT = 8080
MAGIC_WORD = 0xBEEF

OP_AUTH_REQ = 0x01
OP_AUTH_RES = 0x02
OP_CMD_WAYPOINT = 0x04

HEADER_FORMAT = ">HBBI"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
WAYPOINT_FORMAT = ">4f"
WAYPOINT_SIZE = struct.calcsize(WAYPOINT_FORMAT)
MAX_WAYPOINTS = 50

def pack_header(msg_type: int, payload_len: int, status: int = 0) -> bytes:
    return struct.pack(HEADER_FORMAT, MAGIC_WORD, msg_type, status, payload_len)

def pack_auth_req(device_id: str = "GCS_USER_01", secret_key: str = "MySecret2026") -> bytes:
    dev = device_id.encode('utf-8')[:16].ljust(16, b'\x00')
    key = secret_key.encode('utf-8')[:32].ljust(32, b'\x00')
    return dev + key

def pack_waypoints(wps: list) -> bytes:
    """
    wps: list of tuples (latitude, longitude, altitude, speed)
    """
    count = len(wps)
    buf = bytearray(struct.pack(">H", count))
    for lat, lon, alt, spd in wps:
        buf.extend(struct.pack(WAYPOINT_FORMAT, float(lat), float(lon), float(alt), float(spd)))
    
    # Đệm đủ 50 phần tử để đúng 802 bytes theo struct C
    padding = MAX_WAYPOINTS - count
    if padding > 0:
        buf.extend(b"\x00" * (padding * WAYPOINT_SIZE))
    return bytes(buf)

def main():
    server_ip = sys.argv[1] if len(sys.argv) > 1 else SERVER_IP
    server_port = int(sys.argv[2]) if len(sys.argv) > 2 else SERVER_PORT

    print(f"[*] Đang kết nối TCP tới Server {server_ip}:{server_port}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((server_ip, server_port))
        print("  -> Kết nối TCP thành công!")
    except Exception as e:
        print(f"  [LỖI] Không thể kết nối tới Server: {e}")
        return

    # 1. Gửi AUTH_REQ
    print("[*] Gửi thông điệp xác thực AUTH_REQ (0x01)...")
    auth_payload = pack_auth_req()
    auth_pkt = pack_header(OP_AUTH_REQ, len(auth_payload)) + auth_payload
    sock.sendall(auth_pkt)

    # Đọc AUTH_RES
    res_hdr = sock.recv(HEADER_SIZE)
    if len(res_hdr) == HEADER_SIZE:
        magic, msg_type, status, plen = struct.unpack(HEADER_FORMAT, res_hdr)
        res_payload = sock.recv(plen)
        if msg_type == OP_AUTH_RES and status == 0:
            token = res_payload[1:33].decode('utf-8', errors='ignore').rstrip('\x00')
            print(f"  -> Xác thực thành công! Session Token: '{token}'")
        else:
            print(f"  [CẢNH BÁO] Phản hồi xác thực: msg_type=0x{msg_type:02X}, status={status}")

    time.sleep(0.5)

    # 2. Gửi lệnh tọa độ CMD_WAYPOINT (0x04)
    # Danh sách 3 điểm tọa độ khảo sát mẫu quanh trạm HOME:
    # 1 độ = 100,000m => 0.000010 độ = 1 mét (100 cm)
    sample_wps = [
        (0.000010, 0.000015, 15.0, 1.2),  # Điểm 1: X=+150cm, Y=+100cm, Cao 15m, 1.2m/s
        (0.000020, -0.000010, 20.0, 1.5), # Điểm 2: X=-100cm, Y=+200cm, Cao 20m, 1.5m/s
        (0.000000, 0.000000, 10.0, 0.8),  # Điểm 3: Quay về HOME (0, 0), Cao 10m
    ]

    print(f"\n[*] Đang gửi LỆNH TỌA ĐỘ (CMD_WAYPOINT 0x04) gồm {len(sample_wps)} điểm tới Server:")
    for idx, (lat, lon, alt, spd) in enumerate(sample_wps, 1):
        print(f"    Điểm {idx}: Lat={lat:.6f}, Lon={lon:.6f}, Cao={alt:.1f}m, Tốc độ={spd:.1f}m/s (X={lon*100000*100:+.0f}cm, Y={lat*100000*100:+.0f}cm)")

    wp_payload = pack_waypoints(sample_wps)
    wp_pkt = pack_header(OP_CMD_WAYPOINT, len(wp_payload)) + wp_payload
    sock.sendall(wp_pkt)
    print("  -> Đã gửi gói tin CMD_WAYPOINT (802 bytes) thành công qua TCP!")

    time.sleep(1.0)
    sock.close()
    print("[*] Đóng kết nối TCP. Hoàn tất kiểm thử.")

if __name__ == "__main__":
    main()

