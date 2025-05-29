import os
import logging
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, send_file
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from pathlib import Path
import atexit
import io
import pandas as pd

# Import our modules
from jira import JiraAPI
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

app = Flask(__name__, static_folder='static')
app.secret_key = os.getenv("SECRET_KEY", "jira-discord-notifier-secret")


# Add explicit favicon route
@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('favicon.ico')


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
    Reopening is defined as bugs that go from "Reviewing" state back to "Todo" or "In Progress"
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

    # Only look at bugs from the last day to improve performance
    from datetime import datetime, timedelta
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    today = datetime.now().strftime("%Y-%m-%d")

    logger.info(f"Checking for bugs reopened between {yesterday} and {today}")
    reopened_bugs = []

    # Process each project separately to improve performance
    for project_key in project_keys:
        project_reopened_bugs = jira_api.find_reopened_bugs_by_jql(
            project_key,
            start_date=yesterday,
            end_date=today
        )
        logger.info(f"Found {len(project_reopened_bugs)} reopened bugs in project {project_key}")
        reopened_bugs.extend(project_reopened_bugs)

    logger.info(f"Found total of {len(reopened_bugs)} reopened bugs to notify about")

    notifications_sent = 0
    for bug in reopened_bugs:
        issue_key = bug.get('key')
        project_key = bug.get('fields', {}).get('project', {}).get('key')

        # Check if reopen event happened within our time range
        reopen_time_str = bug.get('reopen_time')
        if not reopen_time_str:
            logger.warning(f"Bug {issue_key} marked as reopened but has no reopen_time, skipping")
            continue

        try:
            # Parse the reopen timestamp and check if it's within our time range
            reopen_time = datetime.strptime(reopen_time_str.split('T')[0], "%Y-%m-%d")
            reopen_date_str = reopen_time.strftime("%Y-%m-%d")

            if reopen_date_str < yesterday or reopen_date_str > today:
                logger.info(
                    f"Bug {issue_key} was reopened on {reopen_date_str}, outside our time range {yesterday}-{today}, skipping")
                continue
        except Exception as e:
            logger.error(f"Error parsing reopen time for bug {issue_key}: {str(e)}")
            continue

        # Create a unique key for this specific reopen event
        # This prevents duplicate notifications for the same reopen event
        from_status = bug.get('reopen_from', 'Unknown')
        to_status = bug.get('reopen_to', 'Unknown')
        reopened_by = bug.get('reopen_by', 'Unknown')
        notification_key = f"{issue_key}-reopen-{reopen_time_str}"

        # Check if we've already notified about this specific reopen event
        if jira_api.was_issue_notified('bugs', notification_key):
            logger.info(f"Bug {issue_key} reopen event from {reopen_time_str} already notified, skipping")
            continue

        # Get project-specific webhook URL if available
        webhook_url = project_manager.get_project_webhook(project_key, discord_notifier.default_webhook_url)

        # Add transition info if available
        transition_info = f"from '{from_status}' to '{to_status}'"

        # Add reopen details for the Discord notifier
        bug['reopen_details'] = {
            'from': from_status,
            'to': to_status,
            'by': reopened_by,
            'when': reopen_time_str
        }

        # Send notification with transition info
        result = discord_notifier.send_bug_reopened_notification(bug, webhook_url, transition_info)

        # Mark as processed if notification was sent
        if result:
            jira_api.mark_issue_notified('bugs', notification_key, f"reopened: {transition_info} by {reopened_by}")
            notifications_sent += 1

    logger.info(f"Sent {notifications_sent} new reopen notifications out of {len(reopened_bugs)} reopened bugs found")


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


@app.route('/excel-template', methods=['GET'])
def get_excel_template():
    """
    Generate and return a sample Excel template for task creation
    """
    import io
    import pandas as pd
    from datetime import datetime, timedelta

    # Create a sample dataframe with template columns
    today = datetime.now()
    tomorrow = today + timedelta(days=1)
    next_week = today + timedelta(days=7)

    # Create sample data
    sample_data = [
        {
            "Summary": "Implement login functionality",
            "Description": "Create login form with username and password validation",
            "Type": "Task",
            "Priority": "High",
            "Estimate Time (h)": 5,
            "Story Points": "3",
            "Start Date": today.strftime("%m/%d/%Y"),
            "Notes": "Follow security best practices"
        },
        {
            "Summary": "Design database schema",
            "Description": "Create ERD and define table relationships",
            "Type": "Epic",
            "Priority": "Medium",
            "Estimate Time (h)": 8,
            "Story Points": "5",
            "Start Date": today.strftime("%m/%d/%Y"),
            "Notes": "Consider scaling requirements"
        },
        {
            "Summary": "Fix homepage layout issues",
            "Description": "Fix responsive design problems on mobile devices",
            "Type": "Bug",
            "Priority": "Low",
            "Estimate Time (h)": 3.5,
            "Story Points": "2",
            "Start Date": today.strftime("%m/%d/%Y"),
            "Notes": "Test on multiple device sizes"
        }
    ]

    # Create DataFrame
    df = pd.DataFrame(sample_data)

    # Add empty row with just headers
    empty_row = {column: "" for column in df.columns}
    df = pd.concat([df, pd.DataFrame([empty_row])], ignore_index=True)

    # Create Excel in memory
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Tasks', index=False)

        # Get workbook and worksheet objects
        workbook = writer.book
        worksheet = writer.sheets['Tasks']

        # Add some formatting
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#D9E1F2',
            'border': 1
        })

        # Apply header format
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_format)

        # Adjust column widths
        for i, col in enumerate(df.columns):
            max_len = max(df[col].astype(str).map(len).max(), len(col)) + 2
            worksheet.set_column(i, i, max_len)

        # Add data validation for Type and Priority columns
        # Find column indexes
        type_col_idx = df.columns.get_loc("Type")
        priority_col_idx = df.columns.get_loc("Priority")
        start_date_col_idx = df.columns.get_loc("Start Date")

        # Add dropdown validation for Type column
        type_validation = {
            'validate': 'list',
            'source': ['Task', 'Epic', 'Story', 'Bug']
        }
        worksheet.data_validation(1, type_col_idx, len(df) + 10, type_col_idx, type_validation)

        # Add dropdown validation for Priority column
        priority_validation = {
            'validate': 'list',
            'source': ['Highest', 'High', 'Medium', 'Low', 'Lowest']
        }
        worksheet.data_validation(1, priority_col_idx, len(df) + 10, priority_col_idx, priority_validation)

        # Set date format for Start Date column
        date_format = workbook.add_format({'num_format': 'mm/dd/yyyy'})
        worksheet.set_column(start_date_col_idx, start_date_col_idx, None, date_format)

        # Add a documentation sheet
        doc_sheet = workbook.add_worksheet('Instructions')
        doc_sheet.write(0, 0, 'Task Import Template Instructions', workbook.add_format({'bold': True, 'font_size': 14}))
        doc_sheet.write(1, 0, 'This template is used to create multiple Jira tasks and epics at once.')
        doc_sheet.write(3, 0, 'Column Descriptions:', workbook.add_format({'bold': True}))

        instructions = [
            ['Summary', 'Required. A brief title for the task.'],
            ['Description', 'Optional. A detailed description of the task.'],
            ['Type', 'Optional. Select the issue type (Task, Epic, Story, Bug).'],
            ['Priority', 'Optional. Task priority: Highest, High, Medium, Low, or Lowest.'],
            ['Estimate Time (h)',
             'Optional. Time estimation in hours (can include decimals, e.g., 2.5 for 2 hours 30 minutes).'],
            ['Story Points', 'Optional. Story point value for agile estimations.'],
            ['Start Date', 'Optional. When work should begin, in MM/DD/YYYY format.'],
            ['Notes', 'Optional. Any additional notes or comments.']
        ]

        for i, (col, desc) in enumerate(instructions):
            doc_sheet.write(4 + i, 0, col, workbook.add_format({'bold': True}))
            doc_sheet.write(4 + i, 1, desc)

        doc_sheet.set_column(0, 0, 15)
        doc_sheet.set_column(1, 1, 70)

    # Prepare response
    output.seek(0)

    # Set headers for Excel download
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='jira_tasks_template.xlsx'
    )


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

    # Safely read current .env content
    try:
        with open('.env', 'r') as f:
            env_lines = f.readlines()
    except FileNotFoundError:
        env_lines = []

    # Settings to be explicitly managed and written
    # Convert boolean values to lowercase strings 'true'/'false' for consistency with .env loading
    managed_settings = {
        'DISCORD_WEBHOOK_URL': discord_url,
        'CHECK_INTERVAL': str(check_interval)
    }
    for key, value in new_global_notification_settings.items():
        managed_settings[key.upper()] = str(value).lower()

    # Write to .env
    with open('.env', 'w') as f:
        # Write lines from original .env, skipping those we manage to avoid duplication
        # and to ensure their values are updated from managed_settings.
        written_keys_from_managed = set()  # To track which managed keys were found and replaced

        for line in env_lines:
            stripped_line = line.strip()
            is_managed_line = False
            if '=' in stripped_line:
                key_part = stripped_line.split('=', 1)[0]
                if key_part in managed_settings:
                    # This line is for a setting we are managing.
                    # We will write its new value from managed_settings later.
                    # So, we effectively skip writing the old version here.
                    is_managed_line = True
                    # We don't need to add to written_keys_from_managed here,
                    # as we are just deciding whether to write the original line or not

            if not is_managed_line:
                f.write(line)  # Write unmanaged lines or lines whose keys are not in managed_settings

        # Now write all managed settings, ensuring they are present and up-to-date.
        # This also adds any managed settings that were not in the original .env file.
        for key, value in managed_settings.items():
            f.write(f"{key}={value}\n")

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

    # Get custom field IDs once
    # IMPORTANT: Replace these with the actual names of your custom fields in Jira if they differ.
    epic_link_field_id = jira_api.get_field_id_by_name("Epic Link")
    story_points_field_id = jira_api.get_field_id_by_name("Story Points")  # Or "Story Points Estimate"
    start_date_field_id = jira_api.get_field_id_by_name("Start Date")
    epic_name_field_id = jira_api.get_field_id_by_name("Epic Name")  # For creating Epics

    if not epic_link_field_id:
        logger.warning("Could not find 'Epic Link' custom field ID. Epic linking will be disabled.")
    if not story_points_field_id:
        logger.warning("Could not find 'Story Points' custom field ID. Story points will not be set.")
    if not start_date_field_id:
        logger.warning("Could not find 'Start Date' custom field ID. Start dates will not be set.")
    if not epic_name_field_id:
        logger.warning(
            "Could not find 'Epic Name' custom field ID. Epic creation might be affected if this field is required for Epics.")

    for task_detail in tasks_data:
        epic_key_to_link = None
        task_type = task_detail.get("Type", "Task")
        issue_type = task_type  # Use Type directly as the issue type

        # Only process Epic linking if this is not an Epic itself and has an epic field
        if issue_type != "Epic" and task_detail.get("epic"):
            epic_name_from_task = task_detail.get("epic")

            logger.info(f"Processing Epic '{epic_name_from_task}' for task '{task_detail.get('Summary')}'.")
            try:
                found_epic = jira_api.find_epic_by_name(project_key, epic_name_from_task)

                if found_epic and found_epic.get("key"):
                    epic_key_to_link = found_epic.get("key")
                    logger.info(f"Found existing Epic '{epic_name_from_task}' with key {epic_key_to_link}.")
                else:
                    logger.info(
                        f"Epic '{epic_name_from_task}' not found in project {project_key}. Attempting to create it.")

                    new_epic_payload = {
                        "summary": epic_name_from_task,
                        "issuetype": "Epic",  # Ensure issuetype is correctly "Epic"
                        # Potentially add project key here if create_issue doesn't take it as a separate param for epics
                        # "project": {"key": project_key}, # Depending on your create_issue implementation for Epics
                    }
                    if epic_name_field_id:  # Required for some Jira setups (especially classic)
                        new_epic_payload[epic_name_field_id] = epic_name_from_task
                    else:
                        logger.warning(
                            f"Epic Name custom field ID not found. Creating Epic '{epic_name_from_task}' without setting specific Epic Name field. Summary will be used.")

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
                            "task_summary_related": task_detail.get("Summary"),
                            "message": error_message_epic,
                            "details": created_epic_response
                        })
                        logger.error(
                            f"Failed to create Epic '{epic_name_from_task}' for task '{task_detail.get('Summary')}': {error_message_epic}")
                        continue  # Skip creating task if its epic failed
            except AttributeError as e:
                logger.error(
                    f"`jira_api.find_epic_by_name` or `jira_api.create_issue` method might have an issue or a required field ID was not found: {e}")
                all_successful = False
                results.append({
                    "status": "error_finding_or_creating_epic",
                    "epic_name_attempted": epic_name_from_task,
                    "task_summary_related": task_detail.get("Summary"),
                    "message": "Server misconfiguration or error in Epic processing logic."
                })
                continue  # Skip creating task if its epic failed
            except Exception as e:
                logger.error(
                    f"An unexpected error occurred during Epic processing for '{epic_name_from_task}': {str(e)}")
                all_successful = False
                results.append({
                    "status": "error_processing_epic",
                    "epic_name_attempted": epic_name_from_task,
                    "task_summary_related": task_detail.get("Summary"),
                    "message": f"Unexpected error processing epic: {str(e)}"
                })
                continue  # Skip creating task if its epic failed

        # Prepare issue_payload for the task
        issue_payload = {
            "summary": task_detail.get("Summary"),
            "issuetype": {"name": issue_type},  # Jira usually expects issuetype as an object with name or id
            # "project": {"key": project_key}, # Included in create_issue call, not in payload itself generally
        }

        # Description
        description_parts = []
        if task_detail.get("Description"):
            description_parts.append(task_detail.get("Description"))
        if task_detail.get("Notes"):
            description_parts.append(f"\\n\\nNotes:\\n{task_detail.get('Notes')}")
        if description_parts:
            issue_payload["description"] = "".join(description_parts)

        # Priority
        if task_detail.get("Priority"):
            issue_payload["priority"] = {"name": task_detail.get("Priority")}  # Priority is also often an object

        # Epic Link
        if epic_key_to_link and epic_link_field_id:
            issue_payload[epic_link_field_id] = epic_key_to_link
        elif epic_key_to_link and not epic_link_field_id:
            logger.warning(
                f"Cannot link task '{task_detail.get('Summary')}' to Epic '{epic_key_to_link}'. 'Epic Link' custom field ID not found.")

        # Time Tracking (Original Estimate)
        if task_detail.get("Estimate Time (h)"):
            try:
                estimate_hours = float(task_detail.get("Estimate Time (h)"))
                # Jira expects time in seconds or specific format like "1w 2d 3h 30m"
                # For simplicity, converting hours to seconds. Some Jira instances might also accept "5h" directly.
                # The standard field is `timetracking` which is an object.
                issue_payload["timetracking"] = {
                    "originalEstimate": f"{estimate_hours}h"  # e.g., "5h", "2.5h"
                    # "originalEstimate": int(estimate_hours * 3600) # in seconds
                }
            except ValueError:
                logger.warning(
                    f"Invalid format for 'Estimate Time (h)': {task_detail.get('Estimate Time (h)')}. Skipping.")

        # Start Date
        if task_detail.get("Start Date") and start_date_field_id:
            try:
                # Convert MM/DD/YYYY from Excel to YYYY-MM-DD for Jira
                start_date_obj = datetime.strptime(task_detail.get("Start Date"), "%m/%d/%Y")
                issue_payload[start_date_field_id] = start_date_obj.strftime("%Y-%m-%d")
            except ValueError:
                logger.warning(
                    f"Invalid date format for 'Start Date': {task_detail.get('Start Date')}. Expected MM/DD/YYYY. Skipping.")
        elif task_detail.get("Start Date") and not start_date_field_id:
            logger.warning(
                f"Cannot set Start Date for task '{task_detail.get('Summary')}'. 'Start Date' custom field ID not found.")

        # Story Points
        if task_detail.get("Story Points") and story_points_field_id:
            try:
                story_points_value = float(task_detail.get("Story Points"))
                issue_payload[story_points_field_id] = story_points_value
            except ValueError:
                logger.warning(
                    f"Invalid format for 'Story Points': {task_detail.get('Story Points')}. Must be a number. Skipping.")
        elif task_detail.get("Story Points") and not story_points_field_id:
            logger.warning(
                f"Cannot set Story Points for task '{task_detail.get('Summary')}'. 'Story Points' custom field ID not found.")

        # Fix Version(s) - Jira expects an array of objects by name or ID
        if task_detail.get("fix_version"):
            # Assuming fix_version is a single version name string from input
            # For multiple, you might need to split a comma-separated string
            issue_payload["fixVersions"] = [{"name": task_detail.get("fix_version")}]

        # Sprint ID - This usually needs to be the numeric ID of the sprint.
        # Linking to sprint often happens *after* issue creation via a separate Agile API endpoint.
        # The `create_issue` payload might not directly support adding to sprint for all Jira versions/setups.
        # If your `jira_api.create_issue` handles `sprint_id` internally, this is fine.
        # Otherwise, you'd call `jira_api.add_issue_to_sprint(sprint_id, issue_key)` after successful creation.
        sprint_id_to_link = task_detail.get("sprint_id")

        logger.info(f"Attempting to create Jira task for project {project_key}. Payload: {issue_payload}")
        result = jira_api.create_issue(project_key, issue_payload)

        if result and not result.get("error") and result.get("key"):
            created_issue_key = result.get("key")
            results.append(
                {"status": "success", "task_summary": task_detail.get("Summary"), "issue_key": created_issue_key,
                 "linked_epic_key": epic_key_to_link if epic_key_to_link else "N/A"})

            # If sprint_id is provided and issue created, try to add to sprint
            if sprint_id_to_link:
                logger.info(f"Attempting to add issue {created_issue_key} to sprint {sprint_id_to_link}")
                sprint_add_success = jira_api.add_issue_to_sprint(sprint_id_to_link, created_issue_key)
                if sprint_add_success:
                    logger.info(f"Successfully added {created_issue_key} to sprint {sprint_id_to_link}.")
                else:
                    logger.warning(
                        f"Failed to add {created_issue_key} to sprint {sprint_id_to_link}. Task created but not added to sprint.")
                    # Optionally, update the result for this task to indicate sprint linking failure
                    for res_item in results:
                        if res_item.get("issue_key") == created_issue_key:
                            res_item["sprint_status"] = f"Failed to add to sprint {sprint_id_to_link}"
                            break
        else:
            all_successful = False
            error_message = "Failed to create task"
            # ... (rest of your existing error handling for task creation) ...
            if result and result.get("message"):
                if isinstance(result.get("message"), dict):
                    if result.get("message").get('errorMessages'):
                        error_message = ", ".join(result.get("message").get('errorMessages'))
                    # Also check for 'errors' which often contains field-specific issues
                    elif result.get("message").get('errors'):
                        field_errors = []
                        for field, msg in result.get("message").get('errors').items():
                            field_errors.append(f"{field}: {msg}")
                        error_message = "; ".join(field_errors) if field_errors else error_message

                elif isinstance(result.get("message"), str):
                    error_message = result.get("message")

            error_details = result if result else "No response or unknown error from Jira API during task creation"
            if isinstance(error_details, dict) and len(str(error_details)) > 1000:  # Truncate large error details
                error_details = {"errorMessages": error_details.get("errorMessages", []),
                                 "errors": error_details.get("errors", {})}  # Keep relevant parts

            results.append({"status": "error_creating_task",
                            "task_summary": task_detail.get("Summary"),
                            "message": error_message,
                            "details": error_details,  # Provide details for debugging
                            "linked_epic_key": epic_key_to_link if epic_key_to_link else "N/A",
                            "payload_sent": issue_payload  # Log the payload for debugging
                            })
            logger.error(
                f"Failed to create task '{task_detail.get('Summary')}': {error_message}. Payload: {issue_payload}. Details: {error_details}")

    if all_successful:
        return jsonify({"status": "success", "message": "All tasks created successfully.", "results": results})
    else:
        # Check if any task was successful, or if all failed due to (e.g.) epic issues before task creation
        if any(r.get("status") == "success" for r in results):
            # HTTP 207 Multi-Status might be appropriate if some operations succeeded and some failed.
            return jsonify({"status": "partial_success",
                            "message": "Some tasks/operations could not be completed. Review results for details.",
                            "results": results}), 207
        else:  # No task creation was successful at all
            return jsonify(
                {"status": "error", "message": "Failed to create any tasks. Please check server logs and task details.",
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


@app.route('/api/project-statistics/<project_key>', methods=['GET'])
def get_project_statistics(project_key):
    """
    Get project statistics including participants, issues by status, and bugs
    """
    if not jira_api.is_configured():
        return jsonify({"status": "error", "message": "Jira API not configured"}), 500

    # Get query parameters for filtering
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    participant = request.args.get('participant')

    # Get project statistics from Jira API
    try:
        statistics = jira_api.get_project_statistics(
            project_key,
            start_date=start_date,
            end_date=end_date,
            participant=participant
        )

        # Ensure we always return valid data even if the statistics
        if not statistics:
            statistics = {
                'total_issues': 0,
                'completed_tasks_count': 0,
                'bugs_count': 0,
                'reopened_bugs_count': 0,
                'status_counts': {},
                'issue_types': {},
                'recent_issues': [],
                'participants': [],
                'total_participants': 0,
                'reopeners': [],
                'assignee_bug_stats': []
            }

        # Ensure important fields always exist
        if 'reopeners' not in statistics:
            statistics['reopeners'] = []

        if 'assignee_bug_stats' not in statistics:
            statistics['assignee_bug_stats'] = []

        if 'recent_issues' not in statistics:
            statistics['recent_issues'] = []

        # Add debug data for frontend
        statistics['_debug'] = {
            'has_error': False,
            'processed_time': datetime.now().isoformat()
        }

        return jsonify({
            "status": "success",
            "statistics": statistics
        })
    except Exception as e:
        logger.error(f"Error getting project statistics: {str(e)}")
        # Return empty but valid statistics structure in case of error
        empty_statistics = {
            'total_issues': 0,
            'completed_tasks_count': 0,
            'bugs_count': 0,
            'reopened_bugs_count': 0,
            'status_counts': {},
            'issue_types': {},
            'recent_issues': [],
            'participants': [],
            'total_participants': 0,
            'reopeners': [],
            'assignee_bug_stats': [],
            '_debug': {
                'has_error': True,
                'error_message': str(e),
                'processed_time': datetime.now().isoformat()
            }
        }

        return jsonify({
            "status": "success",
            "statistics": empty_statistics
        })


@app.route('/api/group-statistics/<category>', methods=['GET'])
def get_group_statistics(category):
    """
    Get aggregated statistics for all projects in a specific category/group
    """
    if not jira_api.is_configured():
        return jsonify({"status": "error", "message": "Jira API not configured"}), 500

    # Get query parameters for filtering
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    participant = request.args.get('participant')

    # Get all projects in this category
    all_projects = jira_api.get_all_projects()
    project_categories = project_manager.get_all_projects_by_category(all_projects)

    # Get projects for this category
    category_projects = project_categories.get(category, [])
    if not category_projects:
        return jsonify({
            "status": "error",
            "message": f"No projects found in category '{category}'"
        }), 404

    # Get project keys
    project_keys = [project['key'] for project in category_projects]

    # Initialize aggregated statistics
    aggregated_stats = {
        "total_issues": 0,
        "completed_tasks_count": 0,
        "reopened_bugs_count": 0,
        "total_participants": 0,
        "reopeners": [],  # Will be a list of [name, count] pairs
        "assignee_bug_stats": [],  # Will be a list of [name, {total, reopened}] pairs
        "participants": [],
        "recent_issues": []
    }

    # Map to keep track of unique participants and their stats
    participants_map = {}
    reopeners_map = {}
    assignee_bug_stats_map = {}
    recent_issues = []

    # Process each project in the category
    for project_key in project_keys:
        # Get statistics for this project
        project_stats = jira_api.get_project_statistics(
            project_key,
            start_date=start_date,
            end_date=end_date,
            participant=participant
        )

        if not project_stats:
            logger.warning(f"Could not get statistics for project {project_key}")
            continue

        # Aggregate numeric data
        aggregated_stats["total_issues"] += project_stats.get("total_issues", 0)
        aggregated_stats["completed_tasks_count"] += project_stats.get("completed_tasks_count", 0)
        aggregated_stats["reopened_bugs_count"] += project_stats.get("reopened_bugs_count", 0)

        # Aggregate reopeners data
        for reopener, count in project_stats.get("reopeners", []):
            if reopener in reopeners_map:
                reopeners_map[reopener] += count
            else:
                reopeners_map[reopener] = count

        # Aggregate assignee bug stats
        for assignee, stats in project_stats.get("assignee_bug_stats", []):
            if assignee in assignee_bug_stats_map:
                assignee_bug_stats_map[assignee]["total"] += stats.get("total", 0)
                assignee_bug_stats_map[assignee]["reopened"] += stats.get("reopened", 0)
            else:
                assignee_bug_stats_map[assignee] = {
                    "total": stats.get("total", 0),
                    "reopened": stats.get("reopened", 0)
                }

        # Aggregate participants data
        for participant in project_stats.get("participants", []):
            participant_key = participant.get("key")
            if not participant_key:
                continue

            if participant_key in participants_map:
                # Update counts
                participants_map[participant_key]["assignedCount"] += participant.get("assignedCount", 0)
                participants_map[participant_key]["reportedCount"] += participant.get("reportedCount", 0)
                participants_map[participant_key]["commentCount"] += participant.get("commentCount", 0)
                participants_map[participant_key]["issueCount"] += participant.get("issueCount", 0)
            else:
                # Add new participant
                participants_map[participant_key] = participant.copy()

        # Collect recent issues (up to 5 per project)
        project_issues = project_stats.get("recent_issues", [])
        if project_issues:
            recent_issues.extend(project_issues[:5])

    # Convert maps back to lists
    aggregated_stats["reopeners"] = sorted(
        [[name, count] for name, count in reopeners_map.items()],
        key=lambda x: x[1],
        reverse=True
    )

    aggregated_stats["assignee_bug_stats"] = sorted(
        [[name, stats] for name, stats in assignee_bug_stats_map.items()],
        key=lambda x: x[1]["total"],
        reverse=True
    )

    aggregated_stats["participants"] = list(participants_map.values())
    aggregated_stats["total_participants"] = len(aggregated_stats["participants"])

    # Sort recent issues by updated date and take the most recent 20
    aggregated_stats["recent_issues"] = sorted(
        recent_issues,
        key=lambda x: x.get("updated", ""),
        reverse=True
    )[:20]

    return jsonify({
        "status": "success",
        "statistics": aggregated_stats,
        "group_info": {
            "name": category,
            "project_count": len(project_keys),
            "project_keys": project_keys
        }
    })


@app.route('/api/project-participants/<project_key>', methods=['GET'])
def get_project_participants(project_key):
    """
    Get all participants (users who have created, commented on, or been assigned to issues) in a project
    """
    if not jira_api.is_configured():
        return jsonify({"status": "error", "message": "Jira API not configured"}), 500

    participants = jira_api.get_project_participants(project_key)
    return jsonify({
        "status": "success",
        "participants": participants
    })


@app.route('/api/project-reopened-bugs/<project_key>', methods=['GET'])
def get_project_reopened_bugs(project_key):
    """
    Get reopened bugs for a specific project, filtered by reopener
    """
    if not jira_api.is_configured():
        return jsonify({"status": "error", "message": "Jira API not configured"}), 500

    # Get query parameters
    reopener = request.args.get('reopener')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    # If no reopener specified, return error
    if not reopener:
        return jsonify({"status": "error", "message": "Reopener parameter is required"}), 400

    # Find reopened bugs for this project
    reopened_bugs = jira_api.find_reopened_bugs_by_jql(
        project_key,
        start_date=start_date,
        end_date=end_date
    )

    # Filter by reopener
    filtered_bugs = [bug for bug in reopened_bugs if bug.get('reopen_by') == reopener]

    return jsonify({
        "status": "success",
        "reopened_bugs": filtered_bugs,
        "count": len(filtered_bugs),
        "project_key": project_key,
        "reopener": reopener
    })


@app.route('/api/multi-group-statistics', methods=['GET'])
def get_multi_group_statistics():
    """
    Get aggregated statistics for multiple selected groups
    """
    if not jira_api.is_configured():
        return jsonify({"status": "error", "message": "Jira API not configured"}), 500

    # Get query parameters for filtering
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    participant = request.args.get('participant')

    # Get the groups parameter (JSON encoded)
    groups_json = request.args.get('groups')
    if not groups_json:
        return jsonify({
            "status": "error",
            "message": "No groups specified"
        }), 400

    try:
        import json
        groups = json.loads(groups_json)
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Invalid groups format: {str(e)}"
        }), 400

    # Get all projects
    all_projects = jira_api.get_all_projects()
    project_categories = project_manager.get_all_projects_by_category(all_projects)

    # Collect all project keys from selected groups
    all_project_keys = []
    for group in groups:
        category_projects = project_categories.get(group, [])
        if category_projects:
            group_project_keys = [project['key'] for project in category_projects]
            all_project_keys.extend(group_project_keys)

    if not all_project_keys:
        return jsonify({
            "status": "error",
            "message": "No projects found in the selected groups"
        }), 404
        
    # Limit the number of projects to process to avoid timeouts
    # If there are too many projects, we'll only process the first 10
    # to ensure the request completes within a reasonable time
    if len(all_project_keys) > 10:
        logger.warning(f"Limiting multi-group statistics to first 10 projects out of {len(all_project_keys)}")
        limited_project_keys = all_project_keys[:10]
    else:
        limited_project_keys = all_project_keys

    # Initialize aggregated statistics
    aggregated_stats = {
        "total_issues": 0,
        "completed_tasks_count": 0,
        "reopened_bugs_count": 0,
        "bugs_count": 0,
        "total_participants": 0,
        "reopeners": [],  # Will be a list of [name, count] pairs
        "assignee_bug_stats": [],  # Will be a list of [name, {total, reopened}] pairs
        "participants": [],
        "recent_issues": [],
        "status_counts": {},
        "issue_types": {}
    }

    # Maps to keep track of unique participants and their stats
    participants_map = {}
    reopeners_map = {}
    assignee_bug_stats_map = {}
    recent_issues = []
    
    # Set a timeout for each project to prevent the entire request from hanging
    import threading
    import time
    
    # Process each project with a timeout
    for project_key in limited_project_keys:
        start_time = time.time()
        try:
            # Get statistics for this project with a timeout of 15 seconds per project
            # to ensure the entire request doesn't hang on a single slow project
            project_stats = jira_api.get_project_statistics(
                project_key,
                start_date=start_date,
                end_date=end_date,
                participant=participant
            )
            
            # Check if we've spent too much time on this project
            if time.time() - start_time > 15:
                logger.warning(f"Project {project_key} statistics took too long, skipping detailed processing")
                # Just add basic stats and continue to next project
                aggregated_stats["total_issues"] += project_stats.get("total_issues", 0)
                continue

            if not project_stats:
                logger.warning(f"Could not get statistics for project {project_key}")
                continue

            # Aggregate numeric data
            aggregated_stats["total_issues"] += project_stats.get("total_issues", 0)
            aggregated_stats["completed_tasks_count"] += project_stats.get("completed_tasks_count", 0)
            aggregated_stats["reopened_bugs_count"] += project_stats.get("reopened_bugs_count", 0)
            aggregated_stats["bugs_count"] += project_stats.get("bugs_count", 0)
            
            # Aggregate status counts
            for status, count in project_stats.get("status_counts", {}).items():
                if status in aggregated_stats["status_counts"]:
                    aggregated_stats["status_counts"][status] += count
                else:
                    aggregated_stats["status_counts"][status] = count
                    
            # Aggregate issue types
            for issue_type, count in project_stats.get("issue_types", {}).items():
                if issue_type in aggregated_stats["issue_types"]:
                    aggregated_stats["issue_types"][issue_type] += count
                else:
                    aggregated_stats["issue_types"][issue_type] = count

            # Aggregate reopeners data
            try:
                reopeners_list = project_stats.get("reopeners", [])
                for reopener_item in reopeners_list:
                    if isinstance(reopener_item, list) and len(reopener_item) == 2:
                        reopener, count = reopener_item
                        if reopener in reopeners_map:
                            reopeners_map[reopener] += count
                        else:
                            reopeners_map[reopener] = count
            except Exception as e:
                logger.error(f"Error processing reopeners data for project {project_key}: {str(e)}")

            # Aggregate assignee bug stats
            try:
                assignee_stats_list = project_stats.get("assignee_bug_stats", [])
                for assignee_item in assignee_stats_list:
                    if isinstance(assignee_item, list) and len(assignee_item) == 2:
                        assignee, stats = assignee_item
                        if assignee in assignee_bug_stats_map:
                            assignee_bug_stats_map[assignee]["total"] += stats.get("total", 0)
                            assignee_bug_stats_map[assignee]["reopened"] += stats.get("reopened", 0)
                        else:
                            assignee_bug_stats_map[assignee] = {
                                "total": stats.get("total", 0),
                                "reopened": stats.get("reopened", 0)
                            }
            except Exception as e:
                logger.error(f"Error processing assignee bug stats for project {project_key}: {str(e)}")

            # Aggregate participants data - limit to 100 participants max
            try:
                participant_count = 0
                for participant in project_stats.get("participants", []):
                    participant_count += 1
                    if participant_count > 100:  # Limit to prevent memory issues
                        break
                        
                    participant_key = participant.get("key")
                    if not participant_key:
                        continue

                    if participant_key in participants_map:
                        # Update counts
                        participants_map[participant_key]["assignedCount"] += participant.get("assignedCount", 0)
                        participants_map[participant_key]["reportedCount"] += participant.get("reportedCount", 0)
                        participants_map[participant_key]["commentCount"] += participant.get("commentCount", 0)
                        participants_map[participant_key]["issueCount"] += participant.get("issueCount", 0)
                    else:
                        # Add new participant
                        participants_map[participant_key] = participant.copy()
            except Exception as e:
                logger.error(f"Error processing participants data for project {project_key}: {str(e)}")

            # Collect recent issues (up to 3 per project to limit data size)
            try:
                project_issues = project_stats.get("recent_issues", [])
                if project_issues:
                    recent_issues.extend(project_issues[:3])
            except Exception as e:
                logger.error(f"Error processing recent issues for project {project_key}: {str(e)}")
                
        except Exception as e:
            logger.error(f"Error processing statistics for project {project_key}: {str(e)}")
            continue
            
        # Check if the overall processing is taking too long
        if time.time() - start_time > 30:  # If we've spent more than 30 seconds total
            logger.warning("Multi-group statistics taking too long, stopping further processing")
            break

    # Convert maps back to lists - limit sizes to prevent large responses
    try:
        # Limit to top 20 reopeners
        reopeners_sorted = sorted(
            [[name, count] for name, count in reopeners_map.items()],
            key=lambda x: x[1],
            reverse=True
        )
        aggregated_stats["reopeners"] = reopeners_sorted[:20] if len(reopeners_sorted) > 20 else reopeners_sorted
    except Exception as e:
        logger.error(f"Error sorting reopeners: {str(e)}")
        aggregated_stats["reopeners"] = []

    try:
        # Limit to top 20 assignees
        assignees_sorted = sorted(
            [[name, stats] for name, stats in assignee_bug_stats_map.items()],
            key=lambda x: x[1]["total"],
            reverse=True
        )
        aggregated_stats["assignee_bug_stats"] = assignees_sorted[:20] if len(assignees_sorted) > 20 else assignees_sorted
    except Exception as e:
        logger.error(f"Error sorting assignee bug stats: {str(e)}")
        aggregated_stats["assignee_bug_stats"] = []

    # Limit participants to 100 max
    participants_list = list(participants_map.values())
    aggregated_stats["participants"] = participants_list[:100] if len(participants_list) > 100 else participants_list
    aggregated_stats["total_participants"] = len(aggregated_stats["participants"])

    # Sort recent issues by updated date and take the most recent 15
    try:
        aggregated_stats["recent_issues"] = sorted(
            recent_issues,
            key=lambda x: x.get("updated", ""),
            reverse=True
        )[:15]
    except Exception as e:
        logger.error(f"Error sorting recent issues: {str(e)}")
        aggregated_stats["recent_issues"] = []

    # Add a note if we limited the projects
    was_limited = len(limited_project_keys) < len(all_project_keys)
    
    return jsonify({
        "status": "success",
        "statistics": aggregated_stats,
        "group_info": {
            "groups": groups,
            "group_count": len(groups),
            "project_count": len(all_project_keys),
            "project_keys": limited_project_keys,
            "limited": was_limited,
            "processed_count": len(limited_project_keys),
            "total_count": len(all_project_keys)
        }
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

    # Ensure static directory exists
    static_dir = Path("static")
    static_dir.mkdir(exist_ok=True)

    # Use PORT from environment or default to 5003
    port = int(os.getenv('PORT', 5001))
    # Use HOST from environment or default to 0.0.0.0
    host = os.getenv('HOST', '0.0.0.0')
    # Start the Flask application
    app.run(host=host, port=port, debug=False)