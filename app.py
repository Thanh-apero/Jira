import os
import json
import requests
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
import pickle
import threading
from pathlib import Path

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "jira-discord-notifier-secret")

# Thiết lập logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("jira_discord.log")
    ]
)
logger = logging.getLogger(__name__)

# Discord webhook URL to send notifications
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL')
# Jira API credentials
JIRA_URL = os.getenv('JIRA_URL')
JIRA_USER_EMAIL = os.getenv('JIRA_USER_EMAIL')
JIRA_API_TOKEN = os.getenv('JIRA_API_TOKEN')
# Thời gian kiểm tra (phút)
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '30'))

# Set up scheduler
scheduler = BackgroundScheduler()
scheduler.start()

# Lưu trữ ID issues đã xử lý
processed_issues = set()
processed_comments = set()
processed_status_changes = set()

# File to store project settings
PROJECT_SETTINGS_FILE = "project_settings.pkl"

# Store watched projects
watched_projects = {}

# Create a lock for thread safety
settings_lock = threading.Lock()


def load_project_settings():
    global watched_projects
    if Path(PROJECT_SETTINGS_FILE).exists():
        with open(PROJECT_SETTINGS_FILE, 'rb') as f:
            watched_projects = pickle.load(f)
    else:
        watched_projects = {}


def save_project_settings():
    with settings_lock:
        with open(PROJECT_SETTINGS_FILE, 'wb') as f:
            pickle.dump(watched_projects, f)


# Load settings on startup
load_project_settings()


def send_discord_notification(title, description, color=16711680, fields=None):
    """
    Send a notification to Discord using webhooks
    """
    if not DISCORD_WEBHOOK_URL:
        logger.error("Discord webhook URL is not configured")
        return

    embed = {
        "title": title,
        "description": description,
        "color": color,  # Red for overdue, change as needed
        "timestamp": datetime.utcnow().isoformat()
    }

    if fields:
        embed["fields"] = fields

    payload = {
        "embeds": [embed]
    }

    try:
        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json=payload
        )

        if response.status_code != 204:
            logger.error(f"Failed to send Discord notification: {response.text}")
        else:
            logger.info("Discord notification sent successfully")
    except Exception as e:
        logger.error(f"Error sending Discord notification: {str(e)}")

def get_jira_auth():
    """
    Return the authentication tuple for Jira API
    """
    return (JIRA_USER_EMAIL, JIRA_API_TOKEN)


def get_all_projects():
    """
    Get all projects from Jira
    """
    if not all([JIRA_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN]):
        return []

    try:
        response = requests.get(
            f"{JIRA_URL}/rest/api/2/project",
            auth=get_jira_auth()
        )

        if response.status_code == 200:
            projects = response.json()
            return [
                {
                    "key": project.get('key'),
                    "name": project.get('name'),
                    "id": project.get('id'),
                    "watched": project.get('key') in watched_projects
                }
                for project in projects
            ]
        else:
            logger.error(f"Failed to fetch projects: {response.text}")
            return []
    except Exception as e:
        logger.error(f"Error getting projects: {str(e)}")
        return []

def check_new_issues():
    """
    Check for new issues created and notify
    """
    if not all([JIRA_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN]):
        logger.error("Jira API credentials not configured")
        return

    if not watched_projects:
        logger.info("No projects are being watched")
        return

    # Calculate one hour ago
    one_hour_ago = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")

    # Create project filter string from watched projects
    project_filter = " OR ".join([f"project = {key}" for key in watched_projects.keys()])

    # JQL query to find new issues in watched projects
    jql = f'created >= "{one_hour_ago}" AND ({project_filter}) ORDER BY created DESC'

    try:
        response = requests.get(
            f"{JIRA_URL}/rest/api/2/search",
            params={
                "jql": jql,
                "fields": "key,summary,issuetype,creator,priority,created,project"
            },
            auth=get_jira_auth()
        )

        if response.status_code == 200:
            issues = response.json().get('issues', [])

            for issue in issues:
                issue_key = issue.get('key')

                # Skip if already processed
                if issue_key in processed_issues:
                    continue

                # Process new issue
                summary = issue.get('fields', {}).get('summary')
                issue_type = issue.get('fields', {}).get('issuetype', {}).get('name')
                creator = issue.get('fields', {}).get('creator', {}).get('displayName')
                priority = issue.get('fields', {}).get('priority', {}).get('name')
                project_key = issue.get('fields', {}).get('project', {}).get('key')
                project_name = issue.get('fields', {}).get('project', {}).get('name')

                # Check for high priority issues
                if priority and priority.lower() in ['highest', 'high']:
                    # Prepare fields for Discord notification
                    fields = [
                        {"name": "Issue Type", "value": issue_type, "inline": True},
                        {"name": "Priority", "value": priority, "inline": True},
                        {"name": "Created By", "value": creator, "inline": True},
                        {"name": "Project", "value": project_name, "inline": True},
                        {"name": "Link", "value": f"{JIRA_URL}/browse/{issue_key}", "inline": False}
                    ]

                    title = f"🔴 High Priority Issue: {issue_key}"
                    description = f"**{summary}**"

                    # Send notification to Discord (Red color)
                    send_discord_notification(title, description, 15158332, fields)
                else:
                    # Prepare fields for Discord notification
                    fields = [
                        {"name": "Issue Type", "value": issue_type, "inline": True},
                        {"name": "Created By", "value": creator, "inline": True},
                        {"name": "Project", "value": project_name, "inline": True},
                        {"name": "Link", "value": f"{JIRA_URL}/browse/{issue_key}", "inline": False}
                    ]

                    title = f"🆕 New Issue Created: {issue_key}"
                    description = f"**{summary}**"

                    # Send notification to Discord (Blue color)
                    send_discord_notification(title, description, 3447003, fields)

                # Mark as processed
                processed_issues.add(issue_key)

                # Limit the size of the processed set
                if len(processed_issues) > 1000:
                    # Remove oldest entries
                    processed_issues.clear()
                    processed_issues.add(issue_key)
        else:
            error_message = "Failed to fetch new issues"
            if response.text:
                try:
                    error_data = response.json()
                    if 'errorMessages' in error_data:
                        error_message += f": {error_data['errorMessages']}"
                except:
                    error_message += f": {response.text}"
            logger.error(error_message)

    except Exception as e:
        logger.error(f"Error checking new issues: {str(e)}")

def check_status_changes():
    """
    Check for status changes and notify
    """
    if not all([JIRA_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN]):
        logger.error("Jira API credentials not configured")
        return

    if not watched_projects:
        logger.info("No projects are being watched")
        return

    # Calculate one hour ago
    one_hour_ago = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")

    # Create project filter string from watched projects
    project_filter = " OR ".join([f"project = {key}" for key in watched_projects.keys()])

    # JQL query to find updated issues in watched projects
    jql = f'updated >= "{one_hour_ago}" AND ({project_filter}) ORDER BY updated DESC'

    try:
        response = requests.get(
            f"{JIRA_URL}/rest/api/2/search",
            params={
                "jql": jql,
                "fields": "key,summary,status,updated,changelog,project",
                "expand": "changelog"
            },
            auth=get_jira_auth()
        )

        if response.status_code == 200:
            issues = response.json().get('issues', [])

            for issue in issues:
                issue_key = issue.get('key')
                changelog = issue.get('changelog', {})
                project_name = issue.get('fields', {}).get('project', {}).get('name', 'Unknown')

                if not changelog:
                    continue

                histories = changelog.get('histories', [])

                for history in histories:
                    history_id = history.get('id')

                    # Skip if already processed
                    if f"{issue_key}-{history_id}" in processed_status_changes:
                        continue

                    history_items = history.get('items', [])

                    for item in history_items:
                        if item.get('field') == 'status':
                            from_status = item.get('fromString')
                            to_status = item.get('toString')
                            updated_by = history.get('author', {}).get('displayName')

                            summary = issue.get('fields', {}).get('summary')

                            # Prepare fields for Discord notification
                            fields = [
                                {"name": "From Status", "value": from_status, "inline": True},
                                {"name": "To Status", "value": to_status, "inline": True},
                                {"name": "Updated By", "value": updated_by, "inline": True},
                                {"name": "Project", "value": project_name, "inline": True},
                                {"name": "Link", "value": f"{JIRA_URL}/browse/{issue_key}", "inline": False}
                            ]

                            title = f"🔄 Issue Status Updated: {issue_key}"
                            description = f"**{summary}**"

                            # Send notification to Discord (Yellow color)
                            send_discord_notification(title, description, 15105570, fields)

                            # Mark as processed
                            processed_status_changes.add(f"{issue_key}-{history_id}")

                            # Limit the size of the processed set
                            if len(processed_status_changes) > 1000:
                                processed_status_changes.clear()
                                processed_status_changes.add(f"{issue_key}-{history_id}")
        else:
            error_message = "Failed to fetch status changes"
            if response.text:
                try:
                    error_data = response.json()
                    if 'errorMessages' in error_data:
                        error_message += f": {error_data['errorMessages']}"
                except:
                    error_message += f": {response.text}"
            logger.error(error_message)

    except Exception as e:
        logger.error(f"Error checking status changes: {str(e)}")

def check_new_comments():
    """
    Check for new comments and notify
    """
    if not all([JIRA_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN]):
        logger.error("Jira API credentials not configured")
        return

    if not watched_projects:
        logger.info("No projects are being watched")
        return

    # Calculate one hour ago
    one_hour_ago = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")

    # Create project filter string from watched projects
    project_filter = " OR ".join([f"project = {key}" for key in watched_projects.keys()])

    # JQL query to find updated issues with comments in watched projects
    jql = f'updated >= "{one_hour_ago}" AND ({project_filter}) ORDER BY updated DESC'

    try:
        response = requests.get(
            f"{JIRA_URL}/rest/api/2/search",
            params={
                "jql": jql,
                "fields": "key,summary,comment,project",
                "maxResults": 15  # Limit results to avoid overload
            },
            auth=get_jira_auth()
        )

        if response.status_code == 200:
            issues = response.json().get('issues', [])

            for issue in issues:
                issue_key = issue.get('key')
                issue_summary = issue.get('fields', {}).get('summary')
                comments = issue.get('fields', {}).get('comment', {})
                project_name = issue.get('fields', {}).get('project', {}).get('name', 'Unknown')

                # Check if comments exist
                if not comments:
                    continue

                comments_list = comments.get('comments', [])
                if not comments_list:
                    continue

                for comment in comments_list:
                    comment_id = comment.get('id')

                    # Skip if already processed
                    if f"{issue_key}-{comment_id}" in processed_comments:
                        continue

                    # Make sure created field exists
                    if 'created' not in comment:
                        continue

                    created = comment.get('created')
                    try:
                        comment_created_date = datetime.fromisoformat(created.replace('Z', '+00:00'))

                        # Check if comment is within the last hour
                        if datetime.now() - comment_created_date > timedelta(hours=1):
                            continue
                    except (ValueError, AttributeError):
                        # Skip if can't process date
                        continue

                    comment_body = comment.get('body', '')
                    comment_author = comment.get('author', {}).get('displayName', 'Unknown')

                    # Limit comment length for display
                    if len(comment_body) > 200:
                        comment_body = comment_body[:197] + "..."

                    # Prepare fields for Discord notification
                    fields = [
                        {"name": "Issue", "value": issue_key, "inline": True},
                        {"name": "Commenter", "value": comment_author, "inline": True},
                        {"name": "Project", "value": project_name, "inline": True},
                        {"name": "Content", "value": comment_body, "inline": False},
                        {"name": "Link", "value": f"{JIRA_URL}/browse/{issue_key}?focusedCommentId={comment_id}",
                         "inline": False}
                    ]

                    title = f"💬 New Comment on Issue: {issue_key}"
                    description = f"**{issue_summary}**"

                    # Send notification to Discord (Teal color)
                    send_discord_notification(title, description, 3066993, fields)

                    # Mark as processed
                    processed_comments.add(f"{issue_key}-{comment_id}")

                    # Limit the size of the processed set
                    if len(processed_comments) > 1000:
                        processed_comments.clear()
                        processed_comments.add(f"{issue_key}-{comment_id}")
        else:
            error_message = "Failed to fetch new comments"
            if response.text:
                try:
                    error_data = response.json()
                    if 'errorMessages' in error_data:
                        error_message += f": {error_data['errorMessages']}"
                except:
                    error_message += f": {response.text}"
            logger.error(error_message)

    except Exception as e:
        logger.error(f"Error checking new comments: {str(e)}")

def check_overdue_issues():
    """
    Check for issues that have passed their due date
    """
    if not all([JIRA_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN]):
        logger.error("Jira API credentials not configured")
        return

    if not watched_projects:
        logger.info("No projects are being watched")
        return

    # Get current date in JQL format
    today = datetime.now().strftime("%Y-%m-%d")

    # Create project filter string from watched projects
    project_filter = " OR ".join([f"project = {key}" for key in watched_projects.keys()])

    # JQL query to find overdue issues in watched projects
    jql = f'duedate < "{today}" AND status != Done AND ({project_filter}) ORDER BY duedate ASC'

    try:
        response = requests.get(
            f"{JIRA_URL}/rest/api/2/search",
            params={"jql": jql, "fields": "key,summary,duedate,assignee,project"},
            auth=get_jira_auth()
        )

        if response.status_code == 200:
            issues = response.json().get('issues', [])

            if issues:
                for issue in issues:
                    issue_key = issue.get('key')
                    summary = issue.get('fields', {}).get('summary')
                    due_date = issue.get('fields', {}).get('duedate', 'Unspecified')
                    project_name = issue.get('fields', {}).get('project', {}).get('name', 'Unknown')

                    # Handle when assignee is None
                    assignee_obj = issue.get('fields', {}).get('assignee')
                    assignee = assignee_obj.get('displayName', 'Unknown') if assignee_obj else 'Unassigned'

                    # Prepare fields for Discord notification
                    fields = [
                        {"name": "Due Date", "value": due_date, "inline": True},
                        {"name": "Assignee", "value": assignee, "inline": True},
                        {"name": "Project", "value": project_name, "inline": True},
                        {"name": "Link", "value": f"{JIRA_URL}/browse/{issue_key}", "inline": False}
                    ]

                    title = f"⚠️ OVERDUE ISSUE: {issue_key}"
                    description = f"**{summary}**"

                    # Send notification to Discord (Red color)
                    send_discord_notification(title, description, 16711680, fields)
        else:
            error_message = "Failed to fetch overdue issues"
            if response.text:
                try:
                    error_data = response.json()
                    if 'errorMessages' in error_data:
                        error_message += f": {error_data['errorMessages']}"
                except:
                    error_message += f": {response.text}"
            logger.error(error_message)

    except Exception as e:
        logger.error(f"Error checking overdue issues: {str(e)}")

def check_upcoming_deadlines(days=3):
    """
    Check and notify about tasks with approaching deadlines within the specified number of days
    """
    if not all([JIRA_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN]):
        logger.error("Jira API credentials not configured")
        return

    if not watched_projects:
        logger.info("No projects are being watched")
        return

    # Calculate today and future date
    today = datetime.now().strftime("%Y-%m-%d")
    future = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")

    # Create project filter string from watched projects
    project_filter = " OR ".join([f"project = {key}" for key in watched_projects.keys()])

    # JQL query to find tasks approaching deadlines in watched projects
    jql = f'duedate >= "{today}" AND duedate <= "{future}" AND ({project_filter}) ORDER BY duedate ASC'

    try:
        response = requests.get(
            f"{JIRA_URL}/rest/api/2/search",
            params={"jql": jql, "fields": "key,summary,duedate,assignee,priority,project"},
            auth=get_jira_auth()
        )

        if response.status_code == 200:
            issues = response.json().get('issues', [])

            for issue in issues:
                issue_key = issue.get('key')
                summary = issue.get('fields', {}).get('summary')
                due_date = issue.get('fields', {}).get('duedate', 'Unspecified')
                project_name = issue.get('fields', {}).get('project', {}).get('name', 'Unknown')

                # Handle when assignee is None
                assignee_obj = issue.get('fields', {}).get('assignee')
                assignee = assignee_obj.get('displayName', 'Unknown') if assignee_obj else 'Unassigned'

                # Handle when priority is None
                priority_obj = issue.get('fields', {}).get('priority')
                priority = priority_obj.get('name', 'Unknown') if priority_obj else 'Unspecified'

                # Prepare fields for Discord notification
                fields = [
                    {"name": "Assignee", "value": assignee, "inline": True},
                    {"name": "Deadline", "value": due_date, "inline": True},
                    {"name": "Priority", "value": priority, "inline": True},
                    {"name": "Project", "value": project_name, "inline": True},
                    {"name": "Link", "value": f"{JIRA_URL}/browse/{issue_key}", "inline": False}
                ]

                title = f"⏰ Upcoming Deadline: {issue_key}"
                description = f"**{summary}**"

                # Send notification to Discord (Orange color)
                send_discord_notification(title, description, 15105570, fields)
        else:
            error_message = "Failed to fetch upcoming issues"
            if response.text:
                try:
                    error_data = response.json()
                    if 'errorMessages' in error_data:
                        error_message += f": {error_data['errorMessages']}"
                except:
                    error_message += f": {response.text}"
            logger.error(error_message)
    except Exception as e:
        logger.error(f"Error checking upcoming deadlines: {str(e)}")


# Scheduled checks for all event types

# Check for new issues (every CHECK_INTERVAL minutes)
@scheduler.scheduled_job('interval', minutes=CHECK_INTERVAL)
def scheduled_new_issue_check():
    logger.info("Running new issue check")
    check_new_issues()


# Check for status changes (every CHECK_INTERVAL minutes)
@scheduler.scheduled_job('interval', minutes=CHECK_INTERVAL)
def scheduled_status_change_check():
    logger.info("Running status change check")
    check_status_changes()


# Check for new comments (every CHECK_INTERVAL minutes)
@scheduler.scheduled_job('interval', minutes=CHECK_INTERVAL)
def scheduled_comment_check():
    logger.info("Running new comment check")
    check_new_comments()


# Check for overdue issues (daily at 9 AM)
@scheduler.scheduled_job('cron', hour=9, minute=0)
def scheduled_overdue_check():
    logger.info("Running overdue issue check")
    check_overdue_issues()


# Check for upcoming deadlines (daily at 9 AM)
@scheduler.scheduled_job('cron', hour=9, minute=0)
def scheduled_upcoming_check():
    logger.info("Running upcoming deadline check")
    check_upcoming_deadlines(3)  # 3 days


# Web interface routes

@app.route('/')
def index():
    """
    Main page showing available projects and settings
    """
    projects = get_all_projects()
    discord_url = DISCORD_WEBHOOK_URL if DISCORD_WEBHOOK_URL else ""
    jira_url = JIRA_URL if JIRA_URL else ""
    return render_template('index.html',
                           projects=projects,
                           jira_url=jira_url,
                           discord_url=discord_url,
                           check_interval=CHECK_INTERVAL)


@app.route('/projects/toggle/<project_key>', methods=['POST'])
def toggle_project(project_key):
    """
    Toggle watching status for a project
    """
    if project_key in watched_projects:
        # Unwatch project
        del watched_projects[project_key]
        status = "unwatched"
    else:
        # Get all projects to find the name
        all_projects = get_all_projects()
        project_name = next((p['name'] for p in all_projects if p['key'] == project_key), project_key)

        # Watch project
        watched_projects[project_key] = {
            'name': project_name,
            'added_at': datetime.now().isoformat()
        }
        status = "watched"

    # Save settings
    save_project_settings()

    return jsonify({"status": "success", "project": project_key, "watch_status": status})


@app.route('/settings/update', methods=['POST'])
def update_settings():
    """
    Update application settings
    """
    global DISCORD_WEBHOOK_URL, CHECK_INTERVAL

    discord_url = request.form.get('discord_webhook_url', '').strip()
    check_interval = request.form.get('check_interval', '30')

    try:
        check_interval = int(check_interval)
        if check_interval < 1 or check_interval > 1440:  # Max 1 day in minutes
            flash('Check interval must be between 1 and 1440 minutes', 'error')
            return redirect(url_for('index'))
    except ValueError:
        flash('Check interval must be a number', 'error')
        return redirect(url_for('index'))

    # Update environment variables
    with open('.env', 'r') as f:
        env_lines = f.readlines()

    with open('.env', 'w') as f:
        for line in env_lines:
            if line.strip().startswith('DISCORD_WEBHOOK_URL='):
                f.write(f'DISCORD_WEBHOOK_URL={discord_url}\n')
            elif line.strip().startswith('CHECK_INTERVAL='):
                f.write(f'CHECK_INTERVAL={check_interval}\n')
            else:
                f.write(line)

    # Update in-memory values
    DISCORD_WEBHOOK_URL = discord_url
    CHECK_INTERVAL = check_interval

    # Reschedule jobs with new interval
    for job in scheduler.get_jobs():
        if job.id in ['scheduled_new_issue_check', 'scheduled_status_change_check', 'scheduled_comment_check']:
            job.reschedule(trigger='interval', minutes=CHECK_INTERVAL)

    flash('Settings updated successfully', 'success')
    return redirect(url_for('index'))


@app.route('/run-checks', methods=['POST'])
def run_manual_checks():
    """
    Run all checks manually
    """
    check_type = request.form.get('check_type', 'all')

    if check_type == 'all' or check_type == 'new_issues':
        check_new_issues()

    if check_type == 'all' or check_type == 'status_changes':
        check_status_changes()

    if check_type == 'all' or check_type == 'comments':
        check_new_comments()

    if check_type == 'all' or check_type == 'overdue':
        check_overdue_issues()

    if check_type == 'all' or check_type == 'upcoming':
        check_upcoming_deadlines()

    flash(f'Manual check ({check_type}) completed', 'success')
    return redirect(url_for('index'))


@app.route('/health', methods=['GET'])
def health_check():
    """
    Simple health check endpoint
    """
    return {"status": "alive", "timestamp": datetime.now().isoformat()}, 200

if __name__ == '__main__':
    logger.info("Starting Jira Discord Notifier Web App")
    # Create templates directory if it doesn't exist
    templates_dir = Path("templates")
    templates_dir.mkdir(exist_ok=True)

    port = int(os.getenv('PORT', 5001))
    host = os.getenv('HOST', '0.0.0.0')
    app.run(host=host, port=port, debug=True)