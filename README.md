# UAV Survey NET - Guide to Setting Up & Cloning

Hệ thống điều khiển thiết bị bay khảo sát môi trường 3 lớp (UAV – Server – Client). Tài liệu này hướng dẫn cách clone và thiết lập môi trường phát triển cho từng thành viên theo cấu trúc dự án tập trung (**Monorepo**).

---

## 📌 Cấu trúc Thư mục Dự án

Toàn bộ dự án được quản lý trong một kho chứa (Repository) duy nhất:

```text
uav-survey-net/
├── esp32_drone/          # Mã nguồn ESP32 / FreeRTOS (Thành viên 1)
├── server/       # Mã nguồn Linux Server C/C++ (Thành viên 2)
└── user/       # Mã nguồn Giao diện Điều khiển GUI (Thành viên 3)
```

---

## 🛠️ Hướng dẫn Clone cho Từng Máy (Sparse Checkout)

Để đảm bảo máy của từng thành viên chỉ làm việc với đúng thư mục phụ trách (tránh rối mã nguồn và giảm dung lượng), nhóm áp dụng tính năng **Sparse Checkout** của Git.

---

### 🚁 1. Máy Thiết bị bay (Thành viên 1 - ESP32 / FreeRTOS)

> **Mục tiêu:** Chỉ tải thư mục `uav/` chứa firmware cho vi điều khiển ESP32.

#### Các bước thực hiện:
```bash
# Bước 1: Khởi tạo repository rỗng và trỏ về GitHub của nhóm
git clone --depth 1 --filter=blob:none --sparse https://github.com/Bminh2005/uav-survey-net.git
cd uav-survey-net

# Bước 2: Thiết lập chỉ tải thư mục uav
git sparse-checkout set esp32_drone
```

#### Biên dịch & Nạp Firmware (PlatformIO / ESP-IDF):
```bash
cd esp32_drone
# Nếu dùng PlatformIO CLI
pio run -t upload
```

---

### 🖥️ 2. Máy Máy chủ Trung tâm (Thành viên 2 - Linux Server C/C++)

> **Mục tiêu:** Chỉ tải thư mục `server/` chạy trên HĐH Linux Server (Ubuntu/Debian).

#### Các bước thực hiện:
```bash
# Bước 1: Khởi tạo repository rỗng trên Linux Server
git clone --depth 1 --filter=blob:none --sparse https://github.com/Bminh2005/uav-survey-net.git
cd uav-survey-net
# Bước 2: Thiết lập chỉ tải thư mục server
git sparse-checkout set server
```

#### Biên dịch & Chạy Server:
```bash
cd server

# Cài đặt thư viện phụ trợ (OpenSSL cho TLS)
sudo apt update && sudo apt install build-essential libssl-dev cmake -y

# Biên dịch mã nguồn
make

# Khởi chạy máy chủ
./bin/uav_server
```

---

### 💻 3. Máy Giao diện Điều khiển (Thành viên 3 - GUI Client App)

> **Mục tiêu:** Chỉ tải thư mục `client/` chứa ứng dụng bảng điều khiển cho Người dùng.

#### Các bước thực hiện:
```bash
# Bước 1: Khởi tạo repository rỗng
git clone --depth 1 --filter=blob:none --sparse https://github.com/Bminh2005/uav-survey-net.git
cd uav-survey-net

# Bước 2: Thiết lập chỉ tải thư mục client
git sparse-checkout set client
```

#### Chạy Ứng dụng Client:
```bash
cd client

# Nếu là dự án Python/PyQt:
pip install -r requirements.txt
python main.py

# Hoặc nếu là dự án C++/Qt:
qmake && make
```

---

## 🔄 Quy trình Đồng bộ & Đẩy Mã nguồn (Git Workflow)

Khi có cập nhật mới trong thư mục của bạn, thực hiện đẩy mã nguồn lên GitHub như bình thường:

```bash
# 1. Kiểm tra các file thay đổi
git status

# 2. Add thay đổi
git add .

# 3. Commit kèm message rõ ràng
git commit -m "feat(uav): Thêm logic Safe RTL khi đứt mạng 3s"

# 4. Đẩy mã nguồn lên nhánh chính
git push origin main
```

---

## ⚡ Trường hợp Clone Toàn bộ Dự án (Tùy chọn)

Dành cho Trưởng nhóm hoặc Giảng viên muốn tải toàn bộ source code cả 3 phần về để nghiệm thu/chấm điểm:

```bash
git clone https://github.com/Bminh2005/uav-survey-control-system.git
```
