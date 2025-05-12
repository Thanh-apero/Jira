import os
import logging
import requests
import re
from datetime import datetime

logger = logging.getLogger(__name__)


class DiscordNotifier:
    def __init__(self, webhook_url=None):
        """Initialize Discord notifier with webhook URL"""
        self.default_webhook_url = webhook_url or os.getenv('DISCORD_WEBHOOK_URL')
        # Map of Jira user display names to Discord user IDs
        self.user_mapping = {
            "Hải Khổng Minh": "1077202167129190460",  # kevin_ocean_
            "tramtn": "896304437851725824",  # ngoctram4978
            "Phạm Xuân Hiếu": "873555727057317978",  # hieupx27052003,
            "Võ Hữu Tuấn": "758925480472346625"
        }

    def is_configured(self):
        """Check if Discord webhook URL is configured"""
        return bool(self.default_webhook_url)

    def get_discord_mention(self, jira_user):
        """Convert a Jira username to a Discord mention if available"""
        if not jira_user:
            return ""

        discord_id = self.user_mapping.get(jira_user)
        if discord_id:
            # Format for Discord mention is <@USER_ID> with the numeric ID
            return f"<@{discord_id}>"
        return ""

    def parse_jira_links(self, text):
        """
        Parse Jira markdown links and convert them to plain format
        Handles formats like:
        - URL|URL|smart-link
        - [display text|URL]
        """
        # Handle cases where URL is duplicated with pipes
        # Example: https://github.com/repo/pull/123|https://github.com/repo/pull/123|smart-link
        pipe_url_pattern = re.compile(r'(https?://[^\s|]+)\|(?:https?://[^\s|]+\|)?(?:smart-link|[^\s|]+)')
        text = pipe_url_pattern.sub(r'\1', text)

        # Handle [text|URL] format
        bracket_link_pattern = re.compile(r'\[([^\]]+)\|(https?://[^\]]+)\]')
        text = bracket_link_pattern.sub(r'\1 (\2)', text)

        return text

    def send_notification(self, title, description, color=16711680, fields=None, webhook_url=None):
        """
        Send a notification to Discord using webhooks
        
        Args:
            title (str): Title of the notification
            description (str): Description text
            color (int): Color code (decimal RGB)
            fields (list): List of field dicts (name, value, inline)
            webhook_url (str): Optional specific webhook URL to use instead of default
        """
        webhook_url = webhook_url or self.default_webhook_url

        if not webhook_url:
            logger.error("Discord webhook URL is not configured")
            return False

        embed = {
            "title": title,
            "description": description,
            "color": color,
            "timestamp": datetime.utcnow().isoformat()
        }

        if fields:
            embed["fields"] = fields

        payload = {
            "embeds": [embed]
        }

        try:
            response = requests.post(
                webhook_url,
                json=payload
            )

            if response.status_code != 204:
                logger.error(f"Failed to send Discord notification: {response.text}")
                return False
            else:
                logger.info("Discord notification sent successfully")
                return True
        except Exception as e:
            logger.error(f"Error sending Discord notification: {str(e)}")
            return False

    def send_new_issue_notification(self, issue, webhook_url=None):
        """Send notification about new issue"""
        if not issue:
            return False

        issue_key = issue.get('key')
        summary = issue.get('fields', {}).get('summary')
        issue_type = issue.get('fields', {}).get('issuetype', {}).get('name')
        creator = issue.get('fields', {}).get('creator', {}).get('displayName')
        priority = issue.get('fields', {}).get('priority', {}).get('name')
        project_key = issue.get('fields', {}).get('project', {}).get('key')
        project_name = issue.get('fields', {}).get('project', {}).get('name')

        # Get assignee info
        assignee_obj = issue.get('fields', {}).get('assignee')
        assignee = assignee_obj.get('displayName', 'Unassigned') if assignee_obj else 'Unassigned'

        # Add mention if applicable
        mention = self.get_discord_mention(assignee)

        # Check for high priority issues
        if priority and priority.lower() in ['highest', 'high']:
            fields = [
                {"name": "Issue Type", "value": issue_type, "inline": True},
                {"name": "Priority", "value": priority, "inline": True},
                {"name": "Created By", "value": creator, "inline": True},
                {"name": "Assignee", "value": assignee, "inline": True},
                {"name": "Project", "value": project_name, "inline": True},
                {"name": "Link", "value": f"{os.getenv('JIRA_URL')}/browse/{issue_key}", "inline": False}
            ]

            title = f"🔴 High Priority Issue: {issue_key}"
            description = f"**{summary}**"
            if mention:
                description += f"\n\n{mention} please check this high priority issue!"

            # Send notification to Discord (Red color)
            return self.send_notification(title, description, 15158332, fields, webhook_url)
        else:
            fields = [
                {"name": "Issue Type", "value": issue_type, "inline": True},
                {"name": "Created By", "value": creator, "inline": True},
                {"name": "Assignee", "value": assignee, "inline": True},
                {"name": "Project", "value": project_name, "inline": True},
                {"name": "Link", "value": f"{os.getenv('JIRA_URL')}/browse/{issue_key}", "inline": False}
            ]

            title = f"🆕 New Issue Created: {issue_key}"
            description = f"**{summary}**"
            if mention:
                description += f"\n\n{mention} this task has been assigned to you."

            # Send notification to Discord (Blue color)
            return self.send_notification(title, description, 3447003, fields, webhook_url)

    def send_status_change_notification(self, issue, from_status, to_status, updated_by, webhook_url=None):
        """Send notification about status change"""
        if not issue:
            return False

        issue_key = issue.get('key')
        summary = issue.get('fields', {}).get('summary')
        project_name = issue.get('fields', {}).get('project', {}).get('name', 'Unknown')

        # Get assignee info
        assignee_obj = issue.get('fields', {}).get('assignee')
        assignee = assignee_obj.get('displayName', 'Unassigned') if assignee_obj else 'Unassigned'

        # Add mention if applicable
        mention = self.get_discord_mention(assignee)

        fields = [
            {"name": "From Status", "value": from_status, "inline": True},
            {"name": "To Status", "value": to_status, "inline": True},
            {"name": "Updated By", "value": updated_by, "inline": True},
            {"name": "Assignee", "value": assignee, "inline": True},
            {"name": "Project", "value": project_name, "inline": True},
            {"name": "Link", "value": f"{os.getenv('JIRA_URL')}/browse/{issue_key}", "inline": False}
        ]

        title = f"🔄 Issue Status Updated: {issue_key}"
        description = f"**{summary}**"
        if mention:
            description += f"\n\n{mention} status has been changed to {to_status}."

        # Send notification to Discord (Yellow color)
        return self.send_notification(title, description, 15105570, fields, webhook_url)

    def send_comment_notification(self, issue, comment_id, comment_body, comment_author, webhook_url=None):
        """Send notification about new comment"""
        if not issue:
            return False

        issue_key = issue.get('key')
        issue_summary = issue.get('fields', {}).get('summary')
        project_name = issue.get('fields', {}).get('project', {}).get('name', 'Unknown')

        # Get assignee info
        assignee_obj = issue.get('fields', {}).get('assignee')
        assignee = assignee_obj.get('displayName', 'Unassigned') if assignee_obj else 'Unassigned'

        # Add mention if applicable
        mention = self.get_discord_mention(assignee)

        # Parse any Jira links in comment body
        parsed_comment_body = self.parse_jira_links(comment_body)

        # Limit comment length for display
        if len(parsed_comment_body) > 200:
            parsed_comment_body = parsed_comment_body[:197] + "..."

        fields = [
            {"name": "Issue", "value": issue_key, "inline": True},
            {"name": "Commenter", "value": comment_author, "inline": True},
            {"name": "Assignee", "value": assignee, "inline": True},
            {"name": "Project", "value": project_name, "inline": True},
            {"name": "Content", "value": parsed_comment_body, "inline": False},
            {"name": "Link", "value": f"{os.getenv('JIRA_URL')}/browse/{issue_key}?focusedCommentId={comment_id}",
             "inline": False}
        ]

        title = f"💬 New Comment on Issue: {issue_key}"
        description = f"**{issue_summary}**"
        if mention:
            description += f"\n\n{mention} a new comment was added to this issue."

        # Send notification to Discord (Teal color)
        return self.send_notification(title, description, 3066993, fields, webhook_url)

    def send_bug_reopened_notification(self, bug, webhook_url=None):
        """Send notification about a bug that has been reopened"""
        if not bug:
            return False

        issue_key = bug.get('key')
        summary = bug.get('fields', {}).get('summary')
        project_name = bug.get('fields', {}).get('project', {}).get('name', 'Unknown')

        # Handle when assignee is None
        assignee_obj = bug.get('fields', {}).get('assignee')
        assignee = assignee_obj.get('displayName', 'Unknown') if assignee_obj else 'Unassigned'

        # Add mention if applicable
        mention = self.get_discord_mention(assignee)

        # Handle when priority is None
        priority_obj = bug.get('fields', {}).get('priority')
        priority = priority_obj.get('name', 'Unknown') if priority_obj else 'Unspecified'

        # Get reopen details if available
        reopen_details = bug.get('reopen_details', {})
        from_status = reopen_details.get('from', 'Unknown').capitalize()
        to_status = reopen_details.get('to', 'Unknown').capitalize()
        reopened_by = reopen_details.get('by', 'Unknown')
        reopen_time = reopen_details.get('when', '')

        # Format the reopened time
        if reopen_time:
            try:
                # Try to parse the timestamp and format it in a more readable way
                reopen_timestamp = datetime.fromisoformat(reopen_time.replace('Z', '+00:00'))
                reopen_time_str = f" on {reopen_timestamp.strftime('%Y-%m-%d %H:%M')}"
            except:
                reopen_time_str = ""
        else:
            reopen_time_str = ""

        fields = [
            {"name": "Project", "value": project_name, "inline": True},
            {"name": "Assignee", "value": assignee, "inline": True},
            {"name": "Priority", "value": priority, "inline": True},
            {"name": "Status Change", "value": f"From '{from_status}' to '{to_status}'", "inline": False},
            {"name": "Reopened By", "value": reopened_by, "inline": True},
            {"name": "Link", "value": f"{os.getenv('JIRA_URL')}/browse/{issue_key}", "inline": False}
        ]

        title = f"🐛 REOPENED BUG: {issue_key}"
        description = f"**{summary}**\n\n⚠️ This bug has been reopened by {reopened_by}{reopen_time_str} and needs attention!"
        if mention:
            description += f"\n\n{mention} this bug has been reopened and needs your attention!"

        # Send notification to Discord (Red color with bug emoji)
        return self.send_notification(title, description, 15548997, fields, webhook_url)

    def send_overdue_notification(self, issue, webhook_url=None):
        """Send notification about overdue issue"""
        if not issue:
            return False

        issue_key = issue.get('key')
        summary = issue.get('fields', {}).get('summary')
        due_date = issue.get('fields', {}).get('duedate', 'Unspecified')
        project_name = issue.get('fields', {}).get('project', {}).get('name', 'Unknown')

        # Handle when assignee is None
        assignee_obj = issue.get('fields', {}).get('assignee')
        assignee = assignee_obj.get('displayName', 'Unknown') if assignee_obj else 'Unassigned'

        # Add mention if applicable
        mention = self.get_discord_mention(assignee)

        fields = [
            {"name": "Due Date", "value": due_date, "inline": True},
            {"name": "Assignee", "value": assignee, "inline": True},
            {"name": "Project", "value": project_name, "inline": True},
            {"name": "Link", "value": f"{os.getenv('JIRA_URL')}/browse/{issue_key}", "inline": False}
        ]

        title = f"⚠️ OVERDUE ISSUE: {issue_key}"
        description = f"**{summary}**"
        if mention:
            description += f"\n\n{mention} this issue is overdue and requires urgent attention!"

        # Send notification to Discord (Red color)
        return self.send_notification(title, description, 16711680, fields, webhook_url)

    def send_upcoming_deadline_notification(self, issue, webhook_url=None):
        """Send notification about upcoming deadline"""
        if not issue:
            return False

        issue_key = issue.get('key')
        summary = issue.get('fields', {}).get('summary')
        due_date = issue.get('fields', {}).get('duedate', 'Unspecified')
        project_name = issue.get('fields', {}).get('project', {}).get('name', 'Unknown')

        # Handle when assignee is None
        assignee_obj = issue.get('fields', {}).get('assignee')
        assignee = assignee_obj.get('displayName', 'Unknown') if assignee_obj else 'Unassigned'

        # Add mention if applicable
        mention = self.get_discord_mention(assignee)

        # Handle when priority is None
        priority_obj = issue.get('fields', {}).get('priority')
        priority = priority_obj.get('name', 'Unknown') if priority_obj else 'Unspecified'

        fields = [
            {"name": "Assignee", "value": assignee, "inline": True},
            {"name": "Deadline", "value": due_date, "inline": True},
            {"name": "Priority", "value": priority, "inline": True},
            {"name": "Project", "value": project_name, "inline": True},
            {"name": "Link", "value": f"{os.getenv('JIRA_URL')}/browse/{issue_key}", "inline": False}
        ]

        title = f"⏰ Upcoming Deadline: {issue_key}"
        description = f"**{summary}**"
        if mention:
            description += f"\n\n{mention} this issue has an upcoming deadline!"

        # Send notification to Discord (Orange color)
        return self.send_notification(title, description, 15105570, fields, webhook_url)