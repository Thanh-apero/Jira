import os
import logging
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from pathlib import Path
import atexit

# Import our modules
from jira_api import JiraAPI
from discord_notifications import DiscordNotifier
from project_management import ProjectManager

# Set up basic logging early for dotenv errors
logging.basicConfig(level=logging.INFO)
basic_logger = logging.getLogger(__name__)

# Load environment variables
try:
    load_dotenv()
except Exception as e:
    basic_logger.warning(f"Could not load .env file: {str(e)}. Continuing with environment variables.")

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

# Default global notification types
DEFAULT_GLOBAL_NOTIFICATION_SETTINGS = {
    "notify_reopened_bugs": True,
    "notify_new_issues": True,
    "notify_status_changes": True,
    "notify_comments": True,
    "notify_overdue_issues": True,
    "notify_upcoming_deadlines": True,
}

# Load global notification settings from environment variables, using defaults if not set
global_notification_settings = DEFAULT_GLOBAL_NOTIFICATION_SETTINGS.copy()
for key, default_value in DEFAULT_GLOBAL_NOTIFICATION_SETTINGS.items():
    env_value = os.getenv(key.upper())
    if env_value is not None:
        global_notification_settings[key] = env_value.lower() == 'true'
    else:
        global_notification_settings[key] = default_value

# Initialize our components
jira_api = JiraAPI()
discord_notifier = DiscordNotifier()
project_manager = ProjectManager()

# Set up scheduler
scheduler = BackgroundScheduler()
scheduler.start()

# Shut down the scheduler when the program exits
atexit.register(lambda: scheduler.shutdown())

@scheduler.scheduled_job('interval', minutes=CHECK_INTERVAL, id='scheduled_bug_check')
def scheduled_bug_check():
    """Run reopened bug check"""
    logger.info("Running reopened bug check")
    check_reopened_bugs()


def check_reopened_bugs():
    """
    Check for bugs that have been reopened and notify
    """
    if not global_notification_settings.get("notify_reopened_bugs"):
        logger.info("Skipping reopened bug check as it's globally disabled.")
        return

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
        project_key = bug.get('fields', {}).get('project', {}).get('key')

        # Get project-specific webhook URL if available
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
    if not global_notification_settings.get("notify_new_issues"):
        logger.info("Skipping new issue check as it's globally disabled.")
        return

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
        project_key = issue.get('fields', {}).get('project', {}).get('key')

        # Get project-specific webhook URL if available
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
    if not global_notification_settings.get("notify_status_changes"):
        logger.info("Skipping status change check as it's globally disabled.")
        return

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
        project_key = issue.get('fields', {}).get('project', {}).get('key')

        # Skip bugs - they are handled by check_reopened_bugs
        issue_type = issue.get('fields', {}).get('issuetype', {}).get('name', '').lower()
        if 'bug' in issue_type:
            logger.debug(f"Skipping status notification for bug {issue_key} as bugs are handled separately")
            continue

        # Process status changes that were added to the issue
        status_changes = issue.get('status_changes', [])

        if not status_changes:
            logger.debug(f"No status changes to process for issue {issue_key}")
            continue

        for change in status_changes:
            history_id = change.get('history_id')
            change_key = f"{issue_key}-{history_id}"
            from_status = change.get('from_status')
            to_status = change.get('to_status')
            updated_by = change.get('updated_by')

            # Get project-specific webhook URL if available
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
    if not global_notification_settings.get("notify_comments"):
        logger.info("Skipping new comment check as it's globally disabled.")
        return

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
        project_key = issue.get('fields', {}).get('project', {}).get('key')

        for comment in new_comments:
            comment_id = comment.get('id')
            comment_key = f"{issue_key}-{comment_id}"

            comment_body = comment.get('body', '')
            comment_author = comment.get('author', {}).get('displayName', 'Unknown')

            # Get project-specific webhook URL if available
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
    if not global_notification_settings.get("notify_overdue_issues"):
        logger.info("Skipping overdue issue check as it's globally disabled.")
        return

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
        project_key = issue.get('fields', {}).get('project', {}).get('key')

        # Get project-specific webhook URL if available
        webhook_url = project_manager.get_project_webhook(project_key, discord_notifier.default_webhook_url)

        # Send notification
        result = discord_notifier.send_overdue_notification(issue, webhook_url)

        # Mark as processed if notification was sent
        if result:
            jira_api.mark_issue_notified('issues', issue_key, "overdue")


def check_upcoming_deadlines(days=1):
    """
    Check and notify about tasks with approaching deadlines
    """
    if not global_notification_settings.get("notify_upcoming_deadlines"):
        logger.info("Skipping upcoming deadline check as it's globally disabled.")
        return

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
        project_key = issue.get('fields', {}).get('project', {}).get('key')

        # Get project-specific webhook URL if available
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
@app.route('/', methods=['GET'])
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
                           check_interval=CHECK_INTERVAL,
                           global_notification_settings=global_notification_settings)


@app.route('/healthz', methods=['GET'])
def health_check_railway():
    """
    Simple health check endpoint for Railway
    """
    # In Railway environment, we want to return 200 as long as the app is running
    # even if services aren't fully configured
    status = {
        "status": "alive",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "jira_configured": jira_api.is_configured(),
            "discord_webhook_configured": bool(discord_notifier.default_webhook_url),
            "scheduler_running": scheduler.running
        },
        "healthy": True  # Always return healthy for Railway
    }

    return status, 200


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
    global CHECK_INTERVAL, global_notification_settings

    discord_url = request.form.get('discord_webhook_url', '').strip()
    check_interval = request.form.get('check_interval', '30')

    # Update global notification settings from form
    new_global_notification_settings = {}
    for key in DEFAULT_GLOBAL_NOTIFICATION_SETTINGS.keys():
        form_value = request.form.get(key)
        new_global_notification_settings[key] = form_value == 'on'

    try:
        check_interval = int(check_interval)
        if check_interval < 1 or check_interval > 1440:
            flash('Check interval must be between 1 and 1440 minutes', 'error')
            return redirect(url_for('index'))
    except ValueError:
        flash('Check interval must be a number', 'error')
        return redirect(url_for('index'))

    with open('.env', 'r') as f:
        env_lines = f.readlines()

    with open('.env', 'w') as f:
        for line in env_lines:
            if line.strip().startswith('DISCORD_WEBHOOK_URL='):
                f.write(f'DISCORD_WEBHOOK_URL={discord_url}\n')
            elif line.strip().startswith('CHECK_INTERVAL='):
                f.write(f'CHECK_INTERVAL={check_interval}\n')
            else:
                is_notification_setting_line = False
                for notify_key in DEFAULT_GLOBAL_NOTIFICATION_SETTINGS.keys():
                    if line.strip().startswith(notify_key.upper() + '='):
                        is_notification_setting_line = True
                        break
                if not is_notification_setting_line:
                    f.write(line)

        for key, value in new_global_notification_settings.items():
            f.write(f"{key.upper()}={value}\n")

    discord_notifier.default_webhook_url = discord_url
    CHECK_INTERVAL = check_interval
    global_notification_settings = new_global_notification_settings

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


@app.route('/projects/create-tasks', methods=['POST'])
def create_jira_tasks():
    data = request.json
    project_key = data.get('project_key')
    tasks_data = data.get('tasks')

    if not project_key or not tasks_data:
        return jsonify({"status": "error", "message": "Missing project key or task data"}), 400

    if not jira_api.is_configured():
        logger.error("Jira API credentials not configured. Cannot create tasks.")
        return jsonify({"status": "error", "message": "Jira API not configured on the server."}), 500

    results = []
    all_successful = True

    for task_detail in tasks_data:
        epic_key_to_link = None
        epic_name_from_task = task_detail.get("epic")

        if epic_name_from_task:
            logger.info(f"Processing Epic '{epic_name_from_task}' for task '{task_detail.get('summary')}'.")
            try:
                # Assumption 1: jira_api has a method to find an epic by its name.
                # This method should return an object with a 'key' or None.
                found_epic = jira_api.find_epic_by_name(project_key, epic_name_from_task)

                if found_epic and found_epic.get("key"):
                    epic_key_to_link = found_epic.get("key")
                    logger.info(f"Found existing Epic '{epic_name_from_task}' with key {epic_key_to_link}.")
                else:
                    logger.info(
                        f"Epic '{epic_name_from_task}' not found in project {project_key}. Attempting to create it.")
                    # Assumption 2: jira_api.create_issue can create an Epic.
                    # The payload expects 'summary' for the Epic's name and 'issuetype' as 'Epic'.
                    # The jira_api module is responsible for mapping this to correct Jira fields for Epic creation (e.g. 'Epic Name' custom field).
                    new_epic_payload = {
                        "summary": epic_name_from_task,
                        "issuetype": "Epic"
                    }
                    created_epic_response = jira_api.create_issue(project_key, new_epic_payload)

                    if created_epic_response and not created_epic_response.get("error") and created_epic_response.get(
                            "key"):
                        epic_key_to_link = created_epic_response.get("key")
                        logger.info(
                            f"Successfully created new Epic '{epic_name_from_task}' with key {epic_key_to_link}.")
                    else:
                        all_successful = False
                        error_message_epic = "Failed to create Epic"
                        if created_epic_response and created_epic_response.get("message"):
                            if isinstance(created_epic_response.get("message"), dict) and created_epic_response.get(
                                    "message").get('errorMessages'):
                                error_message_epic = ", ".join(
                                    created_epic_response.get("message").get('errorMessages'))
                            elif isinstance(created_epic_response.get("message"), str):
                                error_message_epic = created_epic_response.get("message")
                        results.append({
                            "status": "error_creating_epic",
                            "epic_name_attempted": epic_name_from_task,
                            "task_summary_related": task_detail.get("summary"),
                            "message": error_message_epic,
                            "details": created_epic_response
                        })
                        logger.error(
                            f"Failed to create Epic '{epic_name_from_task}' for task '{task_detail.get('summary')}': {error_message_epic}")
            except AttributeError:
                logger.error(
                    "`jira_api.find_epic_by_name` method not found. Please implement it to find epics by name.")
                all_successful = False
                results.append({
                    "status": "error_finding_epic",
                    "epic_name_attempted": epic_name_from_task,
                    "task_summary_related": task_detail.get("summary"),
                    "message": "Server misconfiguration: Epic search functionality not available."
                })
            except Exception as e:
                logger.error(
                    f"An unexpected error occurred during Epic processing for '{epic_name_from_task}': {str(e)}")
                all_successful = False
                results.append({
                    "status": "error_processing_epic",
                    "epic_name_attempted": epic_name_from_task,
                    "task_summary_related": task_detail.get("summary"),
                    "message": f"Unexpected error processing epic: {str(e)}"
                })

        # Prepare issue_payload for the task, only including specified fields
        issue_payload = {
            "summary": task_detail.get("summary"),
            "issuetype": task_detail.get("issuetype", "Task"),  # Default to Task, or get from UI
        }

        if epic_key_to_link:
            # Assumption 3: "epic_link_value" is the correct key your jira_api expects for linking,
            # and it expects the Epic's issue KEY.
            issue_payload["epic_link_value"] = epic_key_to_link

        if task_detail.get("priority"):
            issue_payload["priority"] = task_detail.get("priority")

        # Map estimate_time to original_estimate for Jira
        if task_detail.get("estimate_time"):
            issue_payload["original_estimate"] = task_detail.get("estimate_time")

        if task_detail.get("due_date"):
            issue_payload["duedate"] = task_detail.get("due_date")

        # Thêm start_date nếu có
        if task_detail.get("start_date"):
            issue_payload["start_date"] = task_detail.get("start_date")

        # Thêm story_points nếu có
        if task_detail.get("story_points"):
            issue_payload["story_points"] = task_detail.get("story_points")

        # Thêm fix_version nếu có
        if task_detail.get("fix_version"):
            issue_payload["fix_version"] = task_detail.get("fix_version")

        # Thêm sprint_id nếu có
        if task_detail.get("sprint_id"):
            issue_payload["sprint_id"] = task_detail.get("sprint_id")

        logger.info(f"Creating Jira task for project {project_key} with payload: {issue_payload}")
        result = jira_api.create_issue(project_key, issue_payload)

        if result and not result.get("error") and result.get("key"):
            results.append(
                {"status": "success", "task_summary": task_detail.get("summary"), "issue_key": result.get("key"),
                 "linked_epic_key": epic_key_to_link if epic_key_to_link else "N/A"})
        else:
            all_successful = False
            error_message = "Failed to create task"
            if result and result.get("message"):
                if isinstance(result.get("message"), dict) and result.get("message").get('errorMessages'):
                    error_message = ", ".join(result.get("message").get('errorMessages'))
                elif isinstance(result.get("message"), str):
                    error_message = result.get("message")

            # Include Jira's raw error response if available and not too large or sensitive
            error_details = result if result else "No response from Jira API"
            # Avoid overly verbose logs or responses if 'details' could be huge
            if isinstance(error_details, dict) and len(str(error_details)) > 1000:
                error_details = {"errorMessages": error_details.get("errorMessages", []),
                                 "errors": error_details.get("errors", {})}

            results.append({"status": "error",
                            "task_summary": task_detail.get("summary"),
                            "message": error_message,
                            "details": error_details,
                            "linked_epic_key": epic_key_to_link if epic_key_to_link else "N/A"
                            })
            logger.error(
                f"Failed to create task '{task_detail.get('summary')}': {error_message}. Details: {error_details}")

    if all_successful:
        return jsonify({"status": "success", "message": "All tasks created successfully.", "results": results})
    else:
        # Check if any task was successful, or if all failed due to (e.g.) epic issues before task creation
        if any(r.get("status") == "success" for r in results):
            return jsonify({"status": "partial_success", "message": "Some tasks/operations could not be completed.",
                        "results": results}), 207  # Multi-Status
        else:  # No task creation was successful at all
            return jsonify({"status": "error", "message": "Failed to create any tasks. See details.",
                            "results": results}), 500


@app.route('/health', methods=['GET'])
@app.route('/api/health', methods=['GET'])
def health_check():
    """
    Simple health check endpoint
    Also available at /api/health for API consistency
    """
    # In Railway environment, we want to return 200 as long as the app is running
    # even if services aren't fully configured
    status = {
        "status": "alive",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "jira_configured": jira_api.is_configured(),
            "discord_webhook_configured": bool(discord_notifier.default_webhook_url),
            "scheduler_running": scheduler.running
        },
        "healthy": True  # Always return healthy for Railway
    }

    return status, 200


@app.route('/api/issue-types', methods=['GET'])
def get_issue_types():
    """
    Get all issue types available in Jira
    """
    if not jira_api.is_configured():
        return jsonify({"status": "error", "message": "Jira API not configured"}), 500

    issue_types = jira_api.get_issue_types()
    return jsonify({
        "status": "success",
        "issue_types": issue_types
    })


@app.route('/api/custom-fields', methods=['GET'])
def get_custom_fields():
    """
    Get all custom fields to identify start_date and story_point fields
    """
    if not jira_api.is_configured():
        return jsonify({"status": "error", "message": "Jira API not configured"}), 500

    custom_fields = jira_api.find_custom_fields()
    return jsonify({
        "status": "success",
        "custom_fields": custom_fields
    })


@app.route('/api/project-versions/<project_key>', methods=['GET'])
def get_project_versions(project_key):
    """
    Get all versions for a project
    """
    if not jira_api.is_configured():
        return jsonify({"status": "error", "message": "Jira API not configured"}), 500

    versions = jira_api.get_project_versions(project_key)
    return jsonify({
        "status": "success",
        "versions": versions
    })


@app.route('/api/version-issues/<project_key>/<version_id>', methods=['GET'])
def get_version_issues(project_key, version_id):
    """
    Get issues for a specific version
    """
    if not jira_api.is_configured():
        return jsonify({"status": "error", "message": "Jira API not configured"}), 500

    issues = jira_api.get_issues_by_version(project_key, version_id)
    return jsonify({
        "status": "success",
        "issues": issues
    })


@app.route('/api/project-sprints/<project_key>', methods=['GET'])
def get_project_sprints(project_key):
    """
    Get active and future sprints for a project
    """
    if not jira_api.is_configured():
        return jsonify({"status": "error", "message": "Jira API not configured"}), 500

    sprints = jira_api.get_active_sprints(project_key, use_cache=False)
    return jsonify({
        "status": "success",
        "sprints": sprints
    })


@app.route('/api/issues/<issue_key>', methods=['GET'])
def get_issue_details(issue_key):
    """
    Get detailed information about a specific issue
    """
    if not jira_api.is_configured():
        return jsonify({"status": "error", "message": "Jira API not configured"}), 500

    issue = jira_api.get_issue_details(issue_key)
    if not issue:
        return jsonify({"status": "error", "message": f"Issue {issue_key} not found or access denied"}), 404

    return jsonify({
        "status": "success",
        "issue": issue
    })


@app.route('/api/issues/<issue_key>', methods=['PUT'])
def update_issue(issue_key):
    """
    Update an existing issue
    """
    if not jira_api.is_configured():
        return jsonify({"status": "error", "message": "Jira API not configured"}), 500

    data = request.json
    if not data:
        return jsonify({"status": "error", "message": "No update data provided"}), 400

    result = jira_api.update_issue(issue_key, data)

    if result and not result.get("error"):
        return jsonify({
            "status": "success",
            "message": f"Issue {issue_key} updated successfully"
        })
    else:
        return jsonify({
            "status": "error",
            "message": result.get("message", f"Failed to update issue {issue_key}")
        }), 500


if __name__ == '__main__':
    logger.info("Starting Jira Discord Notifier Web App")
    templates_dir = Path("templates")
    templates_dir.mkdir(exist_ok=True)

    # Use PORT from Railway environment
    port = int(os.environ.get('PORT', 5003))
    # Use HOST from environment or default to 0.0.0.0
    host = os.environ.get('HOST', '0.0.0.0')
    # Log port and host for debugging
    logger.info(f"Starting Flask server on {host}:{port}")
    # Start the Flask application
    app.run(host=host, port=port, debug=False)