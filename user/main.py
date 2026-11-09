"""
Điểm khởi chạy chính (Entry Point) của Ứng dụng Trạm Mặt Đất (GCS Client - Thành viên 3).
Chạy lệnh:
    python main.py
"""

import sys
from PyQt6.QtWidgets import QApplication
from main_window import MainWindow

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
