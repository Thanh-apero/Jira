#!/bin/bash

echo "Starting initialization script..."

# Create static directory and favicon
mkdir -p static
touch static/favicon.ico

# Run the Python initialization script
python railway_startup.py || echo "Initialization script failed but continuing"

# Make sure the log file exists and is writable
touch jira_discord.log
chmod 666 jira_discord.log || true

# Check if templates directory exists, create if not
mkdir -p templates

echo "Initialization complete"