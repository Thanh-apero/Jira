#!/bin/bash

# Kiểm tra xem môi trường ảo có tồn tại không
if [ ! -d "venv" ]; then
    echo "Tạo môi trường ảo Python..."
    python3 -m venv venv
fi

# Kích hoạt môi trường ảo
source venv/bin/activate

# Cài đặt các thư viện cần thiết
echo "Cài đặt các thư viện cần thiết..."
pip install -r requirements.txt

# Kiểm tra file .env
if [ ! -f ".env" ]; then
    echo "Tạo file .env từ .env.example..."
    cp .env.example .env
    echo "QUAN TRỌNG: Hãy cập nhật thông tin trong file .env!"
fi

# Chạy ứng dụng
echo "Khởi động server Jira-Discord Notifier..."
python app.py