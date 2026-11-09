# Ứng dụng Trạm Mặt Đất - Ground Control Station (Thành viên 3)

Thư mục này chứa mã nguồn Ứng dụng Điều khiển & Giám sát UAV (**GCS Client GUI**) viết bằng **Python + PyQt6**.

## 1. Cấu trúc Mã nguồn

- `protocol.py`: Định nghĩa cấu trúc gói tin nhị phân chuẩn **Big-Endian (`>`)** theo đúng `giaothuc.pdf`:
  - `MessageHeader` (`>HBBI`, 8 bytes, `magic = 0xBEEF`, `msg_type`, `status`, `payload_len`)
  - `AuthReqPayload` (`0x01` - 48 bytes), `AuthResPayload` (`0x02` - 33 bytes)
  - `TelemetryPayload` (`0x03` - 34 bytes)
  - `WaypointItem` (16 bytes) & `CmdWaypointPayload` (`0x04` - 802 bytes, tối đa 50 điểm)
  - `CmdActionPayload` (`0x05` - 1 byte: `1=Takeoff`, `2=Land`, `3=RTL`)
  - Hàm đọc TCP chống dính/cắt gói: `recv_exact()` và `recv_tcp_message()`.
- `network_worker.py`: Luồng phụ `TcpClientWorker` và `UdpTelemetryWorker` (`QThread`) xử lý kết nối TCP Port 8080 (xác thực `AUTH_REQ`/`AUTH_RES`, gửi lệnh `CMD_WAYPOINT`, `CMD_ACTION`, phản hồi `PING`/`PONG`) và nhận luồng UDP Telemetry 20Hz trên Port 8081.
- `map_widget.py`: Màn hình Radar 2D hiển thị vị trí ước tính của UAV (đơn vị `cm`) so với trạm `HOME (0, 0)`, hỗ trợ click chọn điểm đích trực tiếp.
- `main_window.py`: Giao diện chính gồm 3 khu vực:
  1. **Khu vực 1 (Connection Panel)**: Nhập Server IP, TCP Port (8080), UDP Port (8081), `device_id`, `secret_key` (có nút Hiện/Ẩn), nút `Kết nối` / `Ngắt`.
  2. **Khu vực 2 (Telemetry Dashboard)**: Độ cao, vận tốc, góc nghiêng Roll/Pitch/Yaw, vị trí ước tính `(X, Y)`, thanh phần trăm Pin và chế độ bay.
  3. **Khu vực 3 (Flight Control Pad & Radar)**: 3 nút lệnh tức thời (`CMD_ACTION` `0x05`: Takeoff, Land, Auto RTL), cụm phím điều hướng D-Pad theo bước `cm` tùy chỉnh (`CMD_WAYPOINT` `0x04`) và màn hình Radar 2D.
- `mock_server.py`: Giả lập Central Server & mô phỏng bay 20Hz để chạy thử nghiệm cục bộ.

---

## 2. Hướng dẫn Cài đặt & Chạy Ứng dụng

### Cài đặt thư viện
```powershell
cd user
pip install -r requirements.txt
```

### Chạy Ứng dụng cùng Mock Server
Mở **2 cửa sổ Terminal (PowerShell)** tại thư mục `user/`:

- **Terminal 1 (Chạy Mock Server TCP 8080 & phát UDP Telemetry 20Hz cổng 8081):**
  ```powershell
  python mock_server.py
  ```
- **Terminal 2 (Mở giao diện GCS Client GUI):**
  ```powershell
  python main.py
  ```
