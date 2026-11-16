#!/usr/bin/env python3
"""
UAV Survey Net - TCP Server (Python Version)
Cung cấp khả năng chạy trực tiếp trên Windows / Linux không cần gcc/make:
- Lắng nghe kết nối TCP trên cổng 8080 (hoặc tùy chỉnh)
- Nhận diện gói tin nhị phân chuẩn giaothuc.pdf (Magic 0xBEEF)
- Nhận và giải mã lệnh gửi tọa độ CMD_WAYPOINT (0x04)
- Hỗ trợ cả Web Client qua HTTP (mở trình duyệt http://localhost:8080)
"""

import socket
import struct
import sys
import threading

PORT = 8080
MAGIC_WORD = 0xBEEF
HEADER_FORMAT = ">HBBI"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
WAYPOINT_FORMAT = ">4f"
WAYPOINT_SIZE = struct.calcsize(WAYPOINT_FORMAT)

OP_AUTH_REQ = 0x01
OP_AUTH_RES = 0x02
OP_CMD_WAYPOINT = 0x04
OP_CMD_ACTION = 0x05
OP_PING = 0x0A
OP_PONG = 0x0B

def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Client ngắt kết nối.")
        buf.extend(chunk)
    return bytes(buf)

def handle_client(sock: socket.socket, addr: tuple):
    print(f"\n[SERVER] Chấp nhận kết nối TCP từ {addr[0]}:{addr[1]}")
    try:
        while True:
            # Xem trước 4 bytes đầu để kiểm tra Web Client HTTP
            peek_data = sock.recv(4, socket.MSG_PEEK)
            if not peek_data:
                break

            if peek_data in (b"GET ", b"POST"):
                http_raw = sock.recv(2048).decode('utf-8', errors='ignore')
                if "POST /api/waypoint" in http_raw or "POST /coordinate" in http_raw:
                    body = http_raw.split("\r\n\r\n", 1)[-1]
                    print("\n" + "=" * 65)
                    print("  🌐 [SERVER] NHẬN ĐƯỢC TỌA ĐỘ TỪ WEB CLIENT (HTTP/JSON)")
                    print("=" * 65)
                    print(f"  Dữ liệu JSON: {body}")
                    print("=" * 65)
                    resp = (
                        "HTTP/1.1 200 OK\r\n"
                        "Content-Type: application/json\r\n"
                        "Access-Control-Allow-Origin: *\r\n"
                        "Content-Length: 27\r\n\r\n"
                        '{"status":"ok","code":0}'
                    )
                    sock.sendall(resp.encode('utf-8'))
                else:
                    html = (
                        "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
                        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>UAV Web Client</title>"
                        "<style>body{font-family:Arial,sans-serif;margin:40px;background:#1e1e2f;color:#fff}"
                        ".box{background:#27293d;padding:25px;border-radius:10px;max-width:450px;margin:auto;box-shadow:0 4px 20px rgba(0,0,0,0.5)}"
                        "input{width:90%;padding:10px;margin:8px 0;background:#1d1d2b;border:1px solid #e14eca;color:#fff;border-radius:5px}"
                        "button{background:#e14eca;color:#fff;padding:12px;border:none;border-radius:5px;cursor:pointer;width:96%;margin-top:15px;font-weight:bold}"
                        "button:hover{background:#ff62e5}#res{margin-top:15px;color:#00f2c3}</style></head>"
                        "<body><div class='box'><h2>🚁 UAV Survey - Gửi Tọa Độ</h2>"
                        "<label>Vĩ độ (Lat):</label><input id='lat' value='0.000100'>"
                        "<label>Kinh độ (Lon):</label><input id='lon' value='0.000150'>"
                        "<label>Độ cao (m):</label><input id='alt' value='20.0'>"
                        "<label>Vận tốc (m/s):</label><input id='spd' value='1.2'>"
                        "<button onclick='send()'>GỬI TỌA ĐỘ QUA TCP/HTTP</button><div id='res'></div></div>"
                        "<script>function send(){"
                        "fetch('/api/waypoint',{method:'POST',headers:{'Content-Type':'application/json'},"
                        "body:JSON.stringify({lat:parseFloat(document.getElementById('lat').value),lon:parseFloat(document.getElementById('lon').value),alt:parseFloat(document.getElementById('alt').value),speed:parseFloat(document.getElementById('spd').value)})})"
                        ".then(r=>r.json()).then(d=>document.getElementById('res').innerText='[OK] Server đã ghi nhận tọa độ!')"
                        ".catch(e=>document.getElementById('res').innerText='[Lỗi] '+e);}</script></body></html>"
                    )
                    sock.sendall(html.encode('utf-8'))
                break

            # Gói nhị phân chuẩn
            hdr_bytes = recv_exact(sock, HEADER_SIZE)
            magic, msg_type, status, plen = struct.unpack(HEADER_FORMAT, hdr_bytes)

            if magic != MAGIC_WORD:
                print(f"[SERVER] Sai Magic: 0x{magic:04X} != 0x{MAGIC_WORD:04X}")
                break

            payload = recv_exact(sock, plen) if plen > 0 else b""

            if msg_type == OP_AUTH_REQ:
                dev = payload[:16].decode('utf-8', errors='ignore').rstrip('\x00')
                key = payload[16:48].decode('utf-8', errors='ignore').rstrip('\x00')
                print(f"[SERVER] Nhận AUTH_REQ (0x01): Device='{dev}', Key='{key}'")
                
                # Trả lời AUTH_RES (0x02)
                res_payload = struct.pack(">B32s", 0, b"TOK_UAV_SURVEY_2026_OK".ljust(32, b'\x00'))
                res_hdr = struct.pack(HEADER_FORMAT, MAGIC_WORD, OP_AUTH_RES, 0, len(res_payload))
                sock.sendall(res_hdr + res_payload)
                print(f"[SERVER] -> Xác thực THÀNH CÔNG cho '{dev}'")

            elif msg_type == OP_CMD_WAYPOINT:
                count = struct.unpack(">H", payload[:2])[0]
                print("\n" + "=" * 65)
                print("  🎯 [SERVER] NHẬN ĐƯỢC LỆNH GỬI TỌA ĐỘ (CMD_WAYPOINT 0x04)")
                print("=" * 65)
                print(f" * Tổng số điểm tọa độ: {count} điểm (Payload: {plen} bytes)")
                print("-" * 65)
                offset = 2
                for i in range(count):
                    lat, lon, alt, spd = struct.unpack(WAYPOINT_FORMAT, payload[offset:offset + WAYPOINT_SIZE])
                    dx_cm = lon * 100000.0 * 100.0
                    dy_cm = lat * 100000.0 * 100.0
                    print(f"  [Điểm {i+1:02d}] Vĩ độ: {lat:+10.6f} | Kinh độ: {lon:+10.6f} | Cao: {alt:5.1f}m | Tốc độ: {spd:4.1f}m/s")
                    print(f"           -> Tọa độ Radar: X = {dx_cm:+7.1f} cm, Y = {dy_cm:+7.1f} cm")
                    offset += WAYPOINT_SIZE
                print("=" * 65)

                # Phản hồi PONG
                pong_hdr = struct.pack(HEADER_FORMAT, MAGIC_WORD, OP_PONG, 0, 0)
                sock.sendall(pong_hdr)

            elif msg_type == OP_CMD_ACTION:
                act = payload[0]
                names = {1: "TAKEOFF (Cất cánh)", 2: "LAND (Hạ cánh)", 3: "RTL (Về trạm)"}
                print(f"[SERVER] Nhận lệnh CMD_ACTION (0x05): {names.get(act, act)}")

            elif msg_type == OP_PING:
                pong_hdr = struct.pack(HEADER_FORMAT, MAGIC_WORD, OP_PONG, 0, 0)
                sock.sendall(pong_hdr)

    except Exception as e:
        pass
    finally:
        sock.close()
        print(f"[SERVER] Client {addr[0]}:{addr[1]} đã ngắt kết nối.")

def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port))
    srv.listen(5)

    print("\n" + "=" * 65)
    print("  🚁 UAV SURVEY NET - TCP SERVER (PYTHON RUNNER)")
    print("=" * 65)
    print(f" * Cổng TCP lắng nghe: {port}")
    print(f" * Magic: 0x{MAGIC_WORD:04X}")
    print(" * Sẵn sàng nhận lệnh tọa độ CMD_WAYPOINT (0x04) qua TCP!")
    print(" * Web Client có thể mở: http://localhost:8080 trên trình duyệt")
    print("=" * 65 + "\n")

    try:
        while True:
            c, a = srv.accept()
            t = threading.Thread(target=handle_client, args=(c, a), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\n[SERVER] Đang dừng máy chủ...")
    finally:
        srv.close()

if __name__ == "__main__":
    main()

