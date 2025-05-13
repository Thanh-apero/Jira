import os
from pathlib import Path

# Ensure necessary directories exist
templates_dir = Path("templates")
templates_dir.mkdir(exist_ok=True)

# Create empty .env file if not exists to prevent load_dotenv errors
env_file = Path(".env")
if not env_file.exists():
    print("Creating empty .env file")
    with open(env_file, "w") as f:
        pass  # Create empty file

# Check if notification_history.json exists, create if not
history_file = Path("notification_history.json")
if not history_file.exists():
    print("Creating empty notification history file")
    with open(history_file, "w") as f:
        f.write("{}")

# Check if project_settings.pkl exists, create if not
settings_file = Path("project_settings.pkl")
if not settings_file.exists():
    print("Creating empty project settings file")
    with open(settings_file, "wb") as f:
        pass  # Create empty file

print("Environment initialization complete")
