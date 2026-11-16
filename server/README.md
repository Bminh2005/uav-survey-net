# 🖥️ UAV Survey Net - Central Server (Thành viên 2)

Mã nguồn Máy chủ Trung tâm (**Central Server**) viết bằng **C/C++ cho Linux** (có kèm phiên bản Python runner để chạy trực tiếp trên Windows/Mac) phục vụ Đề tài 11 - Hệ thống Điều khiển & Giám sát Thiết bị bay Khảo sát Môi trường.

---

## 🎯 Chức Năng Chính

1. **Khởi tạo Máy chủ TCP Socket đa luồng (Multi-threaded TCP Server)**:
   - Lắng nghe kết nối TCP trên cổng mặc định `8080`.
   - Hỗ trợ kết nối đồng thời nhiều Client (GCS GUI Client, Web Client, UAV).
2. **Xác thực Đăng nhập (Handshake)**:
   - Nhận gói `AUTH_REQ` (`0x01` - 48 bytes) chứa `device_id` và `secret_key`.
   - Phản hồi `AUTH_RES` (`0x02` - 33 bytes) kèm `session_token`.
3. **Tiếp nhận & Xử lý Lệnh gửi Tọa độ từ Client qua TCP (`CMD_WAYPOINT` - 0x04)**:
   - Nhận gói tin nhị phân chuẩn 802 bytes chứa danh sách tọa độ (Vĩ độ, Kinh độ, Độ cao, Vận tốc).
   - Cơ chế đọc `recv_exact()` chống dính gói và cắt gói trên luồng TCP (TCP stream fragmentation).
   - Giải mã thứ tự byte Big-Endian (`>`) cho cả số nguyên và số thực 32-bit (`float`).
   - Quy đổi sang khoảng cách centimet (cm) trên hệ tọa độ Radar cục bộ so với trạm `HOME (0, 0)`.
4. **Hỗ trợ giao diện Web Client (HTTP/JSON)**:
   - Tích hợp bộ bắt yêu cầu HTTP trên cùng cổng TCP: Mở trình duyệt `http://localhost:8080` để dùng ngay giao diện Web Client tương tác trực quan hoặc mở file `web/web_client.html`.

---

## 📁 Cấu Trúc Mã Nguồn

```text
server/
├── include/
│   ├── protocol_defs.h      # Định nghĩa struct Header 8B (Magic 0xBEEF), Waypoint, Auth
│   └── tcp_server.h         # Khai báo hàm socket TCP, chống dính gói, chuyển đổi byte-order
├── src/
│   ├── tcp_server.c         # Xử lý nhận gói tin TCP, giải mã CMD_WAYPOINT 0x04
│   └── main.c               # Entrypoint chương trình C
├── web/
│   └── web_client.html      # Giao diện Web Client trực quan gửi tọa độ tới Server
├── scripts/
│   ├── test_client_tcp.py   # Script Python mô phỏng gửi tọa độ qua TCP
│   └── server_py.py         # Bản Server Python chạy trực tiếp trên Windows
├── Makefile                 # Biên dịch mã nguồn C bằng `make`
├── CMakeLists.txt           # Hỗ trợ biên dịch bằng `cmake`
└── README.md
```

---

## 🚀 Hướng Dẫn Biên Dịch & Chạy Server

### Cách 1: Chạy Server C/C++ trên Linux (Ubuntu/Debian)

```bash
# 1. Cài đặt công cụ biên dịch (nếu chưa có)
sudo apt update && sudo apt install build-essential -y

# 2. Biên dịch
cd server
make

# 3. Khởi chạy server trên cổng 8080
./bin/uav_server 8080
```

*(Hoặc dùng CMake)*:
```bash
cmake -B build && cmake --build build
./bin/uav_server
```

---

### Cách 2: Chạy trực tiếp trên Windows bằng Python (Không cần gcc/make)

```powershell
cd server
python scripts/server_py.py 8080
```

---

## 🧪 Kiểm Thử Nhận Tọa Độ Từ Client

### Kịch bản 1: Dùng script Python gửi tọa độ TCP mẫu
Mở một cửa sổ Terminal khác:
```powershell
python server/scripts/test_client_tcp.py 127.0.0.1 8080
```
Server sẽ in ra log chi tiết các điểm tọa độ nhận được:
```text
====================================================================
  🎯 [SERVER] NHẬN ĐƯỢC LỆNH GỬI TỌA ĐỘ (CMD_WAYPOINT - 0x04)
====================================================================
 * Tổng số điểm tọa độ: 3 điểm (Payload: 802 bytes)
--------------------------------------------------------------------
  [Điểm 01] Vĩ độ:  +0.000010 | Kinh độ:  +0.000015 | Độ cao:  15.0m | Tốc độ:  1.2m/s
           -> Tọa độ Radar: X =  +150.0 cm, Y =  +100.0 cm
  [Điểm 02] Vĩ độ:  +0.000020 | Kinh độ:  -0.000010 | Độ cao:  20.0m | Tốc độ:  1.5m/s
           -> Tọa độ Radar: X =  -100.0 cm, Y =  +200.0 cm
  [Điểm 03] Vĩ độ:  +0.000000 | Kinh độ:  +0.000000 | Độ cao:  10.0m | Tốc độ:  0.8m/s
           -> Tọa độ Radar: X =    +0.0 cm, Y =    +0.0 cm
====================================================================
```

### Kịch bản 2: Dùng Giao diện Web Client
1. Khởi chạy Server.
2. Mở trình duyệt Web truy cập: `http://localhost:8080` (hoặc mở trực tiếp file `web/web_client.html`).
3. Click chọn điểm trên Radar và nhấn **"GỬI LỆNH TỌA ĐỘ TỚI SERVER"**.

### Kịch bản 3: Kết nối với GCS Client GUI của Thành viên 3
1. Bật Server (`./bin/uav_server` hoặc `python scripts/server_py.py`).
2. Mở giao diện GCS:
   ```powershell
   cd user
   python main.py
   ```
3. Nhập IP `127.0.0.1`, Port `8080` rồi bấm **"Kết nối"**.
4. Click chuột trên màn hình Radar hoặc bấm các phím điều hướng D-Pad -> Server sẽ nhận và hiển thị ngay các tọa độ được gửi tới!
