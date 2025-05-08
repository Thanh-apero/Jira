# Jira Discord Notifier

A web application that connects Jira Cloud with Discord to send notifications when:

- New issues are created
- Issue statuses change
- New comments are added
- Issues are overdue
- Issues have upcoming deadlines

## Features

1. **Project Selection**: Choose which Jira projects you want to monitor
2. **Web Interface**: Easy-to-use web interface to configure settings
3. **Multiple Notification Types**:
    - New issue notifications
    - Status change notifications
    - Comment notifications
    - Overdue issue reminders
    - Upcoming deadline alerts
    - High priority issue alerts

## Installation

1. Install required libraries:

```bash
pip install -r requirements.txt
```

2. Create `.env` file from `.env.example` and update the environment variables:

```bash
cp .env.example .env
```

3. Update the information in the `.env` file:

```
# Jira Cloud settings
JIRA_URL=https://your-domain.atlassian.net
JIRA_API_TOKEN=your_jira_api_token
JIRA_USER_EMAIL=your_jira_email

# Discord settings
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/your_webhook_url

# Server settings
PORT=5001
HOST=0.0.0.0

# App settings
CHECK_INTERVAL=30 # Interval in minutes
```

## How to Get a Jira API Token

1. Log in to your Atlassian account
2. Go to https://id.atlassian.com/manage-profile/security/api-tokens
3. Click on "Create API token"
4. Give it a name and click "Create"
5. Copy the token and save it in your `.env` file (JIRA_API_TOKEN)

## Discord Webhook Setup

1. Go to your Discord server
2. Right-click the channel where you want to receive notifications
3. Select "Edit Channel" > "Integrations" > "Webhooks" > "New Webhook"
4. Name it and copy the Webhook URL
5. Paste this URL in the `DISCORD_WEBHOOK_URL` variable in your `.env` file

## Running the Application

```bash
python app.py
```

Or use the provided script:

```bash
./run.sh
```

The application will run at `http://0.0.0.0:5001` by default.

## Using the Web Interface

1. Open the web interface in your browser
2. Configure your Discord webhook URL and check interval
3. Select the Jira projects you want to monitor
4. The application will automatically check for updates at the specified interval

## Scheduled Notifications

- New issues, status changes, and comments: Every CHECK_INTERVAL minutes (default 30)
- Overdue tasks and upcoming deadlines: Daily at 9:00 AM

## Docker Support

You can run the application using Docker:

```bash
docker-compose up -d
```