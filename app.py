import os
import logging
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from pathlib import Path

# Import our modules
from jira_api import JiraAPI
from discord_notifications import DiscordNotifier
from project_management import ProjectManager

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "jira-discord-notifier-secret")

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("jira_discord.log")
    ]
)
logger = logging.getLogger(__name__)

# Check interval (minutes)
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '30'))

# Initialize our components
jira_api = JiraAPI()
discord_notifier = DiscordNotifier()
project_manager = ProjectManager()

# Set up scheduler
scheduler = BackgroundScheduler()
scheduler.start()


@scheduler.scheduled_job('interval', minutes=CHECK_INTERVAL, id='scheduled_bug_check')
def scheduled_bug_check():
    """Run reopened bug check"""
    logger.info("Running reopened bug check")
    check_reopened_bugs()


def check_reopened_bugs():
    """
    Check for bugs that have been reopened and notify
    """
    if not jira_api.is_configured():
        logger.error("Jira API credentials not configured")
        return

    project_keys = project_manager.get_watched_project_keys()
    if not project_keys:
        logger.info("No projects are being watched")
        return

    reopened_bugs = jira_api.find_reopened_bugs(project_keys)
    logger.info(f"Found {len(reopened_bugs)} reopened bugs to notify about")

    for bug in reopened_bugs:
        issue_key = bug.get('key')

        # Get project-specific webhook URL if available
        project_key = bug.get('fields', {}).get('project', {}).get('key')
        webhook_url = project_manager.get_project_webhook(project_key, discord_notifier.default_webhook_url)

        # Send notification
        result = discord_notifier.send_bug_reopened_notification(bug, webhook_url)

        # Mark as processed if notification was sent
        if result:
            jira_api.mark_issue_notified('bugs', issue_key, "reopened")


def check_new_issues():
    """
    Check for new issues created and notify
    """
    if not jira_api.is_configured():
        logger.error("Jira API credentials not configured")
        return

    project_keys = project_manager.get_watched_project_keys()
    if not project_keys:
        logger.info("No projects are being watched")
        return

    issues = jira_api.find_new_issues(project_keys)
    logger.info(f"Found {len(issues)} new issues to notify about")

    for issue in issues:
        issue_key = issue.get('key')

        # Get project-specific webhook URL if available
        project_key = issue.get('fields', {}).get('project', {}).get('key')
        webhook_url = project_manager.get_project_webhook(project_key, discord_notifier.default_webhook_url)

        # Send notification
        result = discord_notifier.send_new_issue_notification(issue, webhook_url)

        # Mark as processed if notification was sent
        if result:
            jira_api.mark_issue_notified('issues', issue_key, "new issue")


def check_status_changes():
    """
    Check for status changes and notify
    Exclude bugs from notifications as they are handled by check_reopened_bugs
    """
    if not jira_api.is_configured():
        logger.error("Jira API credentials not configured")
        return

    project_keys = project_manager.get_watched_project_keys()
    if not project_keys:
        logger.info("No projects are being watched")
        return

    issues = jira_api.find_status_changes(project_keys)
    logger.info(f"Found {len(issues)} issues with status changes to examine")

    notifications_sent = 0
    for issue in issues:
        issue_key = issue.get('key')

        # Skip bugs - they are handled by check_reopened_bugs
        issue_type = issue.get('fields', {}).get('issuetype', {}).get('name', '').lower()
        if 'bug' in issue_type:
            logger.debug(f"Skipping status notification for bug {issue_key} as bugs are handled separately")
            continue

        changelog = issue.get('changelog', {})
        if not changelog:
            continue

        histories = changelog.get('histories', [])

        for history in histories:
            history_id = history.get('id')
            change_key = f"{issue_key}-{history_id}"

            # History items already filtered in jira_api.find_status_changes
            history_items = history.get('items', [])

            for item in history_items:
                if item.get('field') == 'status':
                    from_status = item.get('fromString')
                    to_status = item.get('toString')
                    updated_by = history.get('author', {}).get('displayName')

                    # Get project-specific webhook URL if available
                    project_key = issue.get('fields', {}).get('project', {}).get('key')
                    webhook_url = project_manager.get_project_webhook(project_key, discord_notifier.default_webhook_url)

                    # Send notification
                    result = discord_notifier.send_status_change_notification(
                        issue, from_status, to_status, updated_by, webhook_url
                    )

                    # Mark as processed if notification was sent
                    if result:
                        jira_api.mark_issue_notified('status_changes', change_key,
                                                     f"status change: {from_status} to {to_status}")
                        notifications_sent += 1

    logger.info(f"Sent {notifications_sent} status change notifications (excluding bugs)")


def check_new_comments():
    """
    Check for new comments and notify
    """
    if not jira_api.is_configured():
        logger.error("Jira API credentials not configured")
        return

    project_keys = project_manager.get_watched_project_keys()
    if not project_keys:
        logger.info("No projects are being watched")
        return

    issues = jira_api.find_new_comments(project_keys)
    logger.info(f"Found {len(issues)} issues with new comments to notify about")

    for issue in issues:
        issue_key = issue.get('key')
        new_comments = issue.get('new_comments', [])

        # Skip if no new comments
        if not new_comments:
            continue

        for comment in new_comments:
            comment_id = comment.get('id')
            comment_key = f"{issue_key}-{comment_id}"

            comment_body = comment.get('body', '')
            comment_author = comment.get('author', {}).get('displayName', 'Unknown')

            # Get project-specific webhook URL if available
            project_key = issue.get('fields', {}).get('project', {}).get('key')
            webhook_url = project_manager.get_project_webhook(project_key, discord_notifier.default_webhook_url)

            # Send notification
            result = discord_notifier.send_comment_notification(
                issue, comment_id, comment_body, comment_author, webhook_url
            )

            # Mark as processed if notification was sent
            if result:
                jira_api.mark_issue_notified('comments', comment_key, "new comment")


def check_overdue_issues():
    """
    Check for issues that have passed their due date
    """
    if not jira_api.is_configured():
        logger.error("Jira API credentials not configured")
        return

    project_keys = project_manager.get_watched_project_keys()
    if not project_keys:
        logger.info("No projects are being watched")
        return

    issues = jira_api.find_overdue_issues(project_keys)
    logger.info(f"Found {len(issues)} overdue issues to notify about")

    for issue in issues:
        issue_key = issue.get('key')

        # Get project-specific webhook URL if available
        project_key = issue.get('fields', {}).get('project', {}).get('key')
        webhook_url = project_manager.get_project_webhook(project_key, discord_notifier.default_webhook_url)

        # Send notification
        result = discord_notifier.send_overdue_notification(issue, webhook_url)

        # Mark as processed if notification was sent
        if result:
            jira_api.mark_issue_notified('issues', issue_key, "overdue")


def check_upcoming_deadlines(days=3):
    """
    Check and notify about tasks with approaching deadlines
    """
    if not jira_api.is_configured():
        logger.error("Jira API credentials not configured")
        return

    project_keys = project_manager.get_watched_project_keys()
    if not project_keys:
        logger.info("No projects are being watched")
        return

    issues = jira_api.find_upcoming_deadlines(project_keys, days)
    logger.info(f"Found {len(issues)} issues with upcoming deadlines to notify about")

    for issue in issues:
        issue_key = issue.get('key')

        # Get project-specific webhook URL if available
        project_key = issue.get('fields', {}).get('project', {}).get('key')
        webhook_url = project_manager.get_project_webhook(project_key, discord_notifier.default_webhook_url)

        # Send notification
        result = discord_notifier.send_upcoming_deadline_notification(issue, webhook_url)

        # Mark as processed if notification was sent
        if result:
            jira_api.mark_issue_notified('issues', issue_key, "upcoming deadline")


# Schedule jobs
@scheduler.scheduled_job('interval', minutes=CHECK_INTERVAL, id='scheduled_new_issue_check')
def scheduled_new_issue_check():
    logger.info("Running new issue check")
    check_new_issues()


@scheduler.scheduled_job('interval', minutes=CHECK_INTERVAL, id='scheduled_status_change_check')
def scheduled_status_change_check():
    logger.info("Running status change check")
    check_status_changes()


@scheduler.scheduled_job('interval', minutes=CHECK_INTERVAL, id='scheduled_comment_check')
def scheduled_comment_check():
    logger.info("Running new comment check")
    check_new_comments()


@scheduler.scheduled_job('cron', hour=9, minute=0, id='scheduled_overdue_check')
def scheduled_overdue_check():
    logger.info("Running overdue issue check")
    check_overdue_issues()


@scheduler.scheduled_job('cron', hour=9, minute=0, id='scheduled_upcoming_check')
def scheduled_upcoming_check():
    logger.info("Running upcoming deadline check")
    check_upcoming_deadlines(3)  # 3 days

# Web interface routes
@app.route('/')
def index():
    """
    Main page showing available projects and settings
    """
    # Debug logging
    logger.info(f"Jira URL: {jira_api.jira_url}")
    logger.info(f"Jira credentials configured: {jira_api.is_configured()}")

    projects = jira_api.get_all_projects()
    logger.info(f"Projects fetched: {len(projects)}")

    if not projects:
        logger.error("No projects found. This could be due to API credentials, network issues, or API permissions.")

    project_categories = project_manager.get_all_projects_by_category(projects)
    logger.info(f"Project categories: {list(project_categories.keys()) if project_categories else []}")

    discord_url = discord_notifier.default_webhook_url or ""
    jira_url = jira_api.jira_url or ""

    return render_template('index.html',
                           project_categories=project_categories,
                           jira_url=jira_url,
                           discord_url=discord_url,
                           check_interval=CHECK_INTERVAL)

@app.route('/projects/toggle/<project_key>', methods=['POST'])
def toggle_project(project_key):
    """
    Toggle watching status for a project
    """
    # Find project name from all projects
    projects = jira_api.get_all_projects()
    project_name = next((p['name'] for p in projects if p['key'] == project_key), project_key)

    # Toggle project watch status
    status = project_manager.toggle_project_watch(project_key, project_name)

    return jsonify({"status": "success", "project": project_key, "watch_status": status})


@app.route('/projects/webhook', methods=['POST'])
def update_project_webhook():
    """
    Update webhook URL for a specific project
    """
    data = request.json
    project_key = data.get('project_key')
    webhook_url = data.get('webhook_url')

    if not project_key:
        return jsonify({"status": "error", "message": "Project key is required"}), 400

    # Update project webhook
    project_manager.update_project_webhook(project_key, webhook_url)

    return jsonify({"status": "success", "project": project_key})

@app.route('/settings/update', methods=['POST'])
def update_settings():
    """
    Update application settings
    """
    global CHECK_INTERVAL

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
    discord_notifier.default_webhook_url = discord_url
    CHECK_INTERVAL = check_interval

    # Reschedule jobs with new interval
    for job in scheduler.get_jobs():
        if job.id in ['scheduled_new_issue_check', 'scheduled_status_change_check', 'scheduled_comment_check',
                      'scheduled_bug_check']:
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

    if check_type == 'all' or check_type == 'bugs':
        check_reopened_bugs()

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