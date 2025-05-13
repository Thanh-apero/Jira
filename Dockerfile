FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create static directory and ensure favicon exists
RUN mkdir -p static
RUN if [ ! -f static/favicon.ico ]; then touch static/favicon.ico; fi

# Tạo và sử dụng người dùng không phải root
RUN useradd -m appuser
RUN chown -R appuser:appuser /app
USER appuser

# Mở port cho ứng dụng
EXPOSE 5000

# Chạy script khởi tạo và ứng dụng với Gunicorn
CMD ["/bin/bash", "-c", "./init_script.sh && gunicorn --workers 1 --timeout 180 --bind 0.0.0.0:${PORT:-5000} wsgi:app"]