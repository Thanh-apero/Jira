#!/bin/bash

echo "Starting initialization script..."

# Run the Python initialization script
python railway_startup.py

# Make sure the log file exists and is writable
touch jira_discord.log
chmod 666 jira_discord.log

# Check if templates directory exists, create if not
mkdir -p templates

echo "Initialization complete"