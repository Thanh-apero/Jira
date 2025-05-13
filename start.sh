#!/bin/bash

# Set default port if not provided
PORT="${PORT:-5000}"
echo "Starting server on port: $PORT"

# Start gunicorn
exec gunicorn --workers=2 --bind="0.0.0.0:$PORT" wsgi:app