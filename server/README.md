# 🖥️ UAV Survey Net - Central Server (Thành viên 2)

Mã nguồn Máy chủ Trung tâm (**Central Server**) phục vụ Đề tài 11 - Hệ thống Điều khiển & Giám sát Thiết bị bay Khảo sát Môi trường:
- Được viết bằng **C/C++ chuẩn POSIX Linux** (có `Makefile` & `CMakeLists.txt`).
- Kèm theo phiên bản **Python Runner** để có thể chạy và thử nghiệm ngay trên máy Windows/Mac mà không cần cài đặt `gcc`/`make`.

---

## 🎯 Chức Năng Hoàn Chỉnh Của Server

1. **Kênh TCP Lệnh Điều Khiển (Port 8080)**:
   - Tiếp nhận kết nối và xác thực đăng nhập: `AUTH_REQ` (`0x01` - 48 bytes) -> phản hồi `AUTH_RES` (`0x02` - 33 bytes).
   - Tiếp nhận lệnh nạp danh sách tọa độ: `CMD_WAYPOINT` (`0x04` - 802 bytes).
   - Tiếp nhận lệnh can thiệp tức thời: `CMD_ACTION` (`0x05`: 1: Takeoff, 2: Land, 3: RTL).
   - Cơ chế đọc `recv_exact()` chống cắt dính gói tin TCP stream.
2. **Kênh UDP Telemetry Tốc Độ Cao 20Hz (Port 8081)**:
   - **Tích hợp bộ giả lập thiết bị bay (UAV Simulator)**: Do chưa có drone phần cứng, Server tự động mô phỏng động học bay (nội suy tọa độ Vĩ độ, Kinh độ, Độ cao, Vận tốc, Góc hướng Yaw, Mức Pin).
   - **Bắn luồng gói tin nhị phân `TELEMETRY` (`0x03` - 34 bytes) ở chu kỳ 50ms (20Hz) về Client (GCS / Web)**.
3. **Giao Diện Web Client Trực Quan (HTTP & Radar 2D)**:
   - Truy cập ngay `http://localhost:8080` (hoặc mở file `web/web_client.html`) để xem Radar 2D hiển thị Drone di chuyển thời gian thực và click nạp tọa độ.

---

## 📁 Cấu Trúc Mã Nguồn Thư Mục `server/`

```text
server/
├── include/
│   ├── protocol_defs.h      # Khai báo cấu trúc Header 8B (Magic 0xBEEF), Waypoint, Telemetry 34B
│   └── tcp_server.h         # Khai báo TCP Socket, UDP Socket 20Hz, hàm giải mã float Big-Endian
├── src/
│   ├── tcp_server.c         # Logic Server: Tiếp nhận TCP, nạp Waypoints, luồng phát UDP Telemetry 20Hz
│   └── main.c               # Entrypoint chương trình C
├── web/
│   └── web_client.html      # Giao diện Web Client trực quan (HUD + Radar 2D + điều khiển)
├── scripts/
│   ├── server_py.py         # Bản Server Python chạy trực tiếp trên Windows (TCP 8080 & UDP 8081)
│   ├── test_client_tcp.py   # Script Client kiểm thử gửi tọa độ TCP
│   └── run_demo.py          # Kịch bản kiểm thử toàn diện: Gửi TCP & Nhận UDP Telemetry 20Hz
├── Makefile                 # Biên dịch mã nguồn C trên Linux (`make`)
├── CMakeLists.txt           # Biên dịch mã nguồn C bằng `cmake`
└── README.md
```

---

## 🚀 Hướng Dẫn Chạy & Kiểm Thử

### Cách 1: Chạy trực tiếp trên Windows (Khuyên dùng khi chưa có Linux)

Mở PowerShell tại thư mục dự án:
```powershell
# Khởi chạy Server (TCP 8080 & UDP Telemetry 20Hz cổng 8081)
python uav-survey-net/server/scripts/server_py.py
```

Khi Server chạy:
1. **Dùng Web Client**: Mở trình duyệt Web truy cập `http://localhost:8080` (hoặc mở trực tiếp file `server/web/web_client.html`) để xem Drone di chuyển trên Radar theo tọa độ nạp vào.
2. **Dùng GCS Client GUI của Thành viên 3**:
   ```powershell
   cd uav-survey-net/user
   python main.py
   ```
   Bấm **"Kết nối"** (IP `127.0.0.1`, TCP `8080`, UDP `8081`) -> GCS Client sẽ tự động đón luồng UDP Telemetry 20Hz và hiển thị HUD bay thời gian thực!

---

### Cách 2: Chạy Thử Nghiệm Tự Động Toàn Diện
Chạy kịch bản kiểm thử tích hợp (Server nhận tọa độ TCP và bắn UDP Telemetry 20Hz về Client):
```powershell
python uav-survey-net/server/scripts/run_demo.py
```

---

### Cách 3: Biên Dịch & Chạy Server C/C++ trên Linux (Ubuntu/Debian)
```bash
cd server
make
./bin/uav_server 8080 8081
```
