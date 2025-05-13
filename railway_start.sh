#!/bin/bash

# Run the initialization script first
./init_script.sh

# Check if PORT is set
if [ -z "$PORT" ]; then
  echo "PORT environment variable not set, using default 5000"
  PORT=5000
fi

echo "Starting gunicorn on port $PORT"
exec gunicorn --bind "0.0.0.0:$PORT" app:app