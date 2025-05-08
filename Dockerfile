FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Tạo và sử dụng người dùng không phải root
RUN useradd -m appuser
USER appuser

# Mở port cho ứng dụng
EXPOSE 5000

# Chạy ứng dụng với Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]