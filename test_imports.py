#!/usr/bin/env python3
# Test script to identify import errors

print("Starting import test...")

try:
    print("Testing basic imports...")
    import os
    import logging
    from datetime import datetime
    import requests
    print("✓ Basic imports successful")
except Exception as e:
    print(f"✗ Error in basic imports: {str(e)}")

try:
    print("Testing Flask imports...")
    from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
    print("✓ Flask imports successful")
except Exception as e:
    print(f"✗ Error in Flask imports: {str(e)}")

try:
    print("Testing dotenv...")
    from dotenv import load_dotenv
    print("✓ dotenv import successful")
except Exception as e:
    print(f"✗ Error in dotenv import: {str(e)}")

try:
    print("Testing APScheduler...")
    from apscheduler.schedulers.background import BackgroundScheduler
    print("✓ APScheduler import successful")
except Exception as e:
    print(f"✗ Error in APScheduler import: {str(e)}")

try:
    print("Testing pathlib...")
    from pathlib import Path
    print("✓ pathlib import successful")
except Exception as e:
    print(f"✗ Error in pathlib import: {str(e)}")

try:
    print("Testing atexit...")
    import atexit
    print("✓ atexit import successful")
except Exception as e:
    print(f"✗ Error in atexit import: {str(e)}")

try:
    print("Testing local imports...")
    from jira_api import JiraAPI
    from discord_notifications import DiscordNotifier
    from project_management import ProjectManager
    print("✓ Local module imports successful")
except Exception as e:
    print(f"✗ Error in local imports: {str(e)}")

print("Import test completed")
