import os
import logging
import requests
import time
import json
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Path to store notification history
NOTIFICATION_HISTORY_FILE = "notification_history.json"


class JiraAPI:
    def __init__(self, jira_url=None, jira_email=None, jira_token=None):
        """Initialize Jira API with credentials"""
        self.jira_url = jira_url or os.getenv('JIRA_URL')
        self.jira_email = jira_email or os.getenv('JIRA_USER_EMAIL')
        self.jira_token = jira_token or os.getenv('JIRA_API_TOKEN')
        # Add caching to reduce API calls
        self._projects_cache = {}
        self._issues_cache = {}
        self._sprints_cache = {}
        self._cache_expiry = {}
        self._default_cache_time = 30 * 60  # 30 minutes in seconds

        # Load notification history
        self._notification_history = self._load_notification_history()

    @property
    def auth(self):
        """Return auth tuple for requests"""
        return (self.jira_email, self.jira_token)

    def is_configured(self):
        """Check if Jira credentials are configured"""
        return all([self.jira_url, self.jira_email, self.jira_token])

    def _is_cache_valid(self, cache_key):
        """Check if cache is still valid"""
        if cache_key not in self._cache_expiry:
            return False
        return time.time() < self._cache_expiry[cache_key]

    def _set_cache(self, cache_type, cache_key, data, expiry=None):
        """Set cache data with expiry time"""
        if cache_type == 'projects':
            self._projects_cache[cache_key] = data
        elif cache_type == 'issues':
            self._issues_cache[cache_key] = data
        elif cache_type == 'sprints':
            self._sprints_cache[cache_key] = data

        self._cache_expiry[cache_key] = time.time() + (expiry or self._default_cache_time)

    def _load_notification_history(self):
        """Load notification history from file"""
        if Path(NOTIFICATION_HISTORY_FILE).exists():
            try:
                with open(NOTIFICATION_HISTORY_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading notification history: {str(e)}")
                return {"bugs": {}, "issues": {}, "comments": {}, "status_changes": {}}
        else:
            return {"bugs": {}, "issues": {}, "comments": {}, "status_changes": {}}

    def _save_notification_history(self):
        """Save notification history to file"""
        try:
            with open(NOTIFICATION_HISTORY_FILE, 'w') as f:
                json.dump(self._notification_history, f)
        except Exception as e:
            logger.error(f"Error saving notification history: {str(e)}")

    def mark_issue_notified(self, issue_type, issue_key, reason=None):
        """Mark an issue as having been notified about"""
        if issue_type not in self._notification_history:
            self._notification_history[issue_type] = {}

        self._notification_history[issue_type][issue_key] = {
            "timestamp": datetime.now().isoformat(),
            "reason": reason or "general notification"
        }

        # Save to disk
        self._save_notification_history()

    def was_issue_notified(self, issue_type, issue_key):
        """Check if an issue has already been notified about"""
        if issue_type not in self._notification_history:
            return False

        return issue_key in self._notification_history[issue_type]

    def get_all_projects(self, use_cache=True):
        """Get all projects from Jira"""
        cache_key = 'all_projects'

        # Return from cache if valid
        if use_cache and self._is_cache_valid(cache_key) and cache_key in self._projects_cache:
            logger.info(f"Using cached projects data ({len(self._projects_cache[cache_key])} projects)")
            return self._projects_cache[cache_key]

        if not self.is_configured():
            logger.error("Jira API credentials not configured")
            return []

        try:
            logger.info(f"Fetching projects from {self.jira_url}/rest/api/2/project")
            response = requests.get(
                f"{self.jira_url}/rest/api/2/project",
                auth=self.auth
            )

            if response.status_code == 200:
                projects = response.json()
                logger.info(f"Successfully fetched {len(projects)} projects from Jira")

                result = []
                # For efficiency, don't make API calls for categories - determine from naming conventions
                for project in projects:
                    key = project.get('key', '')
                    # Determine category from key pattern
                    if key.startswith('BE') or key.startswith('BACKEND'):
                        category = 'Backend'
                    elif key.startswith('FE') or key.startswith('FRONTEND'):
                        category = 'Frontend'
                    elif key.startswith('MOB') or key.startswith('MOBILE'):
                        category = 'Mobile'
                    elif key.startswith('AIP'):
                        category = 'Software'
                    elif key.startswith('AAIP'):
                        category = 'AI Products'
                    else:
                        category = 'General'

                    result.append({
                        "key": project.get('key'),
                        "name": project.get('name'),
                        "id": project.get('id'),
                        "category": category,
                        "avatarUrl": project.get('avatarUrls', {}).get('48x48', '')
                    })

                logger.info(f"Processed {len(result)} projects with categories")
                # Cache the result
                self._set_cache('projects', cache_key, result)
                return result
            else:
                logger.error(f"Failed to fetch projects: {response.status_code}")
                logger.error(f"Response: {response.text}")
                return []
        except Exception as e:
            logger.error(f"Error getting projects: {str(e)}")
            return []

    def get_active_sprints(self, project_key, use_cache=True):
        """Get active sprints for a project"""
        cache_key = f"active_sprints_{project_key}"

        # Return from cache if valid (short cache time for active sprints)
        if use_cache and self._is_cache_valid(cache_key) and cache_key in self._sprints_cache:
            logger.info(f"Using cached active sprints for {project_key}")
            return self._sprints_cache[cache_key]

        if not self.is_configured():
            logger.error("Jira API credentials not configured")
            return []

        try:
            logger.info(f"Fetching active sprints for project {project_key}")

            # First get all boards for the project
            boards_response = requests.get(
                f"{self.jira_url}/rest/agile/1.0/board",
                params={"projectKeyOrId": project_key},
                auth=self.auth
            )

            if boards_response.status_code != 200:
                logger.error(f"Failed to fetch boards: {boards_response.status_code}")
                return []

            boards = boards_response.json().get('values', [])

            active_sprints = []
            for board in boards:
                board_id = board.get('id')

                # Get active sprints for this board
                sprints_response = requests.get(
                    f"{self.jira_url}/rest/agile/1.0/board/{board_id}/sprint",
                    params={"state": "active"},
                    auth=self.auth
                )

                if sprints_response.status_code == 200:
                    sprints = sprints_response.json().get('values', [])
                    active_sprints.extend(sprints)

            logger.info(f"Found {len(active_sprints)} active sprints for project {project_key}")

            # Cache for a shorter time (5 minutes)
            self._set_cache('sprints', cache_key, active_sprints, 5 * 60)
            return active_sprints

        except Exception as e:
            logger.error(f"Error getting active sprints: {str(e)}")
            return []

    def get_issues_in_active_sprints(self, project_keys, status_filter=None):
        """
        Get issues from active sprints in the specified projects
        
        Args:
            project_keys (list): List of project keys to check
            status_filter (list, optional): List of statuses to include (e.g. ["To Do", "In Progress"])
        """
        if not project_keys:
            return []

        all_issues = []

        for project_key in project_keys:
            active_sprints = self.get_active_sprints(project_key)

            for sprint in active_sprints:
                sprint_id = sprint.get('id')

                # Build JQL query
                jql_parts = [f"sprint = {sprint_id}"]

                if status_filter:
                    status_clause = " OR ".join([f'status = "{status}"' for status in status_filter])
                    jql_parts.append(f"({status_clause})")

                jql = " AND ".join(jql_parts)

                # Get issues in this sprint
                issues = self.search_issues(
                    jql,
                    fields="key,summary,issuetype,assignee,status,priority,created,updated,project",
                    max_results=100,  # Increased limit to get more issues
                    use_cache=False  # Don't cache as sprint contents change frequently
                )

                all_issues.extend(issues)

        return all_issues

    def find_reopened_bugs(self, project_keys):
        """Find reopened bugs in the specified projects"""
        if not project_keys:
            return []

        logger.info(f"Searching for reopened bugs in projects: {', '.join(project_keys)}")

        # First get all bugs in active sprints that are in Todo or In Progress
        bugs_to_check = []

        # Use JQL to find all bugs in todo or in progress
        bug_jql = f"issuetype in ('Bug', 'Defect') AND status in ('To Do', 'In Progress', 'Todo', 'Open') AND project in ({','.join(project_keys)})"

        bugs = self.search_issues(
            bug_jql,
            fields="key,summary,issuetype,assignee,status,priority,created,updated,project",
            max_results=100
        )

        logger.info(f"Found {len(bugs)} active bugs to check for reopen status")

        reopened_bugs = []

        for bug in bugs:
            issue_key = bug.get('key')

            # Skip if already notified
            if self.was_issue_notified('bugs', issue_key):
                continue

            # Get changelog to check for reopen
            issue_detail = self.get_issue_with_changelog(issue_key)
            changelog = issue_detail.get('changelog', {}).get('histories', [])

            # Check if bug was reopened
            was_reopened = False
            reopen_details = None

            for history in changelog:
                for item in history.get('items', []):
                    if item.get('field') == 'status':
                        from_status = item.get('fromString', '').lower()
                        to_status = item.get('toString', '').lower()

                        # If moved from Done/Review/Resolved/Closed to Todo/In Progress
                        if (from_status in ['done', 'review', 'resolved', 'closed'] and
                                to_status in ['to do', 'todo', 'in progress', 'open']):
                            was_reopened = True
                            reopen_details = {
                                'from': from_status,
                                'to': to_status,
                                'by': history.get('author', {}).get('displayName', 'Unknown'),
                                'when': history.get('created', 'Unknown time')
                            }
                            break

                if was_reopened:
                    break

            if was_reopened:
                logger.info(
                    f"Found reopened bug {issue_key}: '{issue_detail.get('fields', {}).get('summary', 'No summary')}'")

                # Add reopen details to the issue for the notification
                issue_detail['reopen_details'] = reopen_details
                reopened_bugs.append(issue_detail)

        logger.info(f"Found {len(reopened_bugs)} reopened bugs that need notification")
        return reopened_bugs

    def get_issue_with_changelog(self, issue_key):
        """Get issue details with changelog"""
        try:
            response = requests.get(
                f"{self.jira_url}/rest/api/2/issue/{issue_key}",
                params={"expand": "changelog"},
                auth=self.auth
            )

            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get issue {issue_key}: {response.status_code}")
                return {}
        except Exception as e:
            logger.error(f"Error getting issue {issue_key}: {str(e)}")
            return {}

    def get_project_category(self, project_id):
        """
        Get project category from Jira
        This is now only used as a fallback - the main categorization is done in get_all_projects
        """
        if not self.is_configured():
            return "Unknown"

        try:
            response = requests.get(
                f"{self.jira_url}/rest/api/2/project/{project_id}",
                auth=self.auth
            )

            if response.status_code == 200:
                project_data = response.json()
                # Try to get category from project data
                if 'projectCategory' in project_data and project_data['projectCategory']:
                    return project_data['projectCategory'].get('name', 'General')
                else:
                    # Check for custom field or naming convention that might indicate category
                    key = project_data.get('key', '')
                    # Check naming patterns
                    if key.startswith('BE') or key.startswith('BACKEND'):
                        return 'Backend'
                    elif key.startswith('FE') or key.startswith('FRONTEND'):
                        return 'Frontend'
                    elif key.startswith('MOB') or key.startswith('MOBILE'):
                        return 'Mobile'
                    elif key.startswith('AIP'):
                        return 'Software'
                    elif key.startswith('AAIP'):
                        return 'AI Products'
                    else:
                        # Default category based on URL pattern
                        if '/software/' in self.jira_url:
                            return 'Software'
                        else:
                            return 'General'
            else:
                return "Unknown"
        except Exception as e:
            logger.error(f"Error getting project category: {str(e)}")
            return "Unknown"

    def search_issues(self, jql, fields=None, max_results=50, expand=None, use_cache=True, expiry=None):
        """Search for issues using JQL"""
        cache_key = f"jql_{jql}_{fields}_{max_results}_{expand}"

        # Return from cache if valid and not for time-sensitive queries
        if use_cache and not ('updated >=' in jql or 'created >=' in jql) and self._is_cache_valid(
                cache_key) and cache_key in self._issues_cache:
            logger.info(f"Using cached issues data for query {jql[:30]}...")
            return self._issues_cache[cache_key]

        if not self.is_configured():
            logger.error("Jira API credentials not configured")
            return []

        if fields is None:
            fields = "key,summary,issuetype,creator,priority,created,project,status,comment,duedate,assignee"

        try:
            logger.info(f"Searching issues with JQL: {jql[:50]}...")
            params = {
                "jql": jql,
                "fields": fields,
                "maxResults": max_results
            }

            if expand:
                params["expand"] = expand

            response = requests.get(
                f"{self.jira_url}/rest/api/2/search",
                params=params,
                auth=self.auth
            )

            if response.status_code == 200:
                result = response.json().get('issues', [])
                # Only cache if not a time-sensitive query
                if use_cache and not ('updated >=' in jql or 'created >=' in jql):
                    self._set_cache('issues', cache_key, result, expiry)
                return result
            else:
                error_message = "Failed to fetch issues"
                if response.text:
                    try:
                        error_data = response.json()
                        if 'errorMessages' in error_data:
                            error_message += f": {error_data['errorMessages']}"
                    except:
                        error_message += f": {response.text}"
                logger.error(error_message)
                return []
        except Exception as e:
            logger.error(f"Error searching issues: {str(e)}")
            return []

    def find_new_issues(self, project_keys, hours=1):
        """Find new issues created within the specified timeframe"""
        if not project_keys:
            return []

        time_ago = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
        project_filter = " OR ".join([f"project = {key}" for key in project_keys])
        status_filter = " AND status in ('To Do', 'In Progress')"
        jql = f'created >= "{time_ago}" AND ({project_filter}){status_filter} ORDER BY created DESC'

        new_issues = self.search_issues(jql, use_cache=False)  # Don't cache time-sensitive queries

        # Filter out issues that have already been notified about
        return [issue for issue in new_issues
                if not self.was_issue_notified('issues', issue.get('key'))]

    def find_status_changes(self, project_keys, hours=1):
        """Find issues with status changes within the specified timeframe"""
        if not project_keys:
            return []

        time_ago = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
        project_filter = " OR ".join([f"project = {key}" for key in project_keys])
        status_filter = " AND status in ('To Do', 'In Progress')"
        jql = f'updated >= "{time_ago}" AND ({project_filter}){status_filter} ORDER BY updated DESC'

        all_issues = self.search_issues(
            jql,
            fields="key,summary,status,updated,project",
            expand="changelog",
            use_cache=False
        )

        # Filter to only include issues with actual status changes
        issues_with_changes = []
        for issue in all_issues:
            issue_key = issue.get('key')
            changelog = issue.get('changelog', {})
            histories = changelog.get('histories', [])

            for history in histories:
                history_id = history.get('id')
                # Skip if already notified about this change
                if self.was_issue_notified('status_changes', f"{issue_key}-{history_id}"):
                    continue

                for item in history.get('items', []):
                    if item.get('field') == 'status':
                        # Only include if changing to Todo or In Progress
                        to_status = item.get('toString', '').lower()
                        if to_status in ['to do', 'todo', 'in progress']:
                            issues_with_changes.append(issue)
                            break

        return issues_with_changes

    def find_new_comments(self, project_keys, hours=1):
        """Find issues with new comments within the specified timeframe"""
        if not project_keys:
            return []

        time_ago = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
        project_filter = " OR ".join([f"project = {key}" for key in project_keys])
        status_filter = " AND status in ('To Do', 'In Progress')"
        jql = f'updated >= "{time_ago}" AND ({project_filter}){status_filter} ORDER BY updated DESC'

        all_issues = self.search_issues(jql, fields="key,summary,comment,project", use_cache=False)

        # Filter to only include issues with new comments
        issues_with_new_comments = []

        for issue in all_issues:
            issue_key = issue.get('key')
            comments = issue.get('fields', {}).get('comment', {})

            if not comments:
                continue

            comments_list = comments.get('comments', [])
            new_comments = []

            for comment in comments_list:
                comment_id = comment.get('id')
                # Skip if already notified about this comment
                if self.was_issue_notified('comments', f"{issue_key}-{comment_id}"):
                    continue

                # Check if comment is recent
                created = comment.get('created', '')
                if created:
                    try:
                        comment_date = datetime.fromisoformat(created.replace('Z', '+00:00'))
                        if datetime.now(comment_date.tzinfo) - comment_date <= timedelta(hours=hours):
                            new_comments.append(comment)
                    except:
                        pass

            if new_comments:
                # Attach the new comments to the issue for processing
                issue['new_comments'] = new_comments
                issues_with_new_comments.append(issue)

        return issues_with_new_comments

    def find_overdue_issues(self, project_keys):
        """Find overdue issues"""
        if not project_keys:
            return []

        today = datetime.now().strftime("%Y-%m-%d")
        project_filter = " OR ".join([f"project = {key}" for key in project_keys])
        status_filter = " AND status in ('To Do', 'In Progress')"
        jql = f'duedate < "{today}"{status_filter} AND ({project_filter}) ORDER BY duedate ASC'

        all_issues = self.search_issues(jql, fields="key,summary,duedate,assignee,project", expiry=15 * 60)

        # Filter out issues that have already been notified about
        return [issue for issue in all_issues
                if not self.was_issue_notified('issues', issue.get('key'))]

    def find_upcoming_deadlines(self, project_keys, days=3):
        """Find issues with upcoming deadlines"""
        if not project_keys:
            return []

        today = datetime.now().strftime("%Y-%m-%d")
        future = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        project_filter = " OR ".join([f"project = {key}" for key in project_keys])
        status_filter = " AND status in ('To Do', 'In Progress')"
        jql = f'duedate >= "{today}" AND duedate <= "{future}"{status_filter} AND ({project_filter}) ORDER BY duedate ASC'

        all_issues = self.search_issues(jql, fields="key,summary,duedate,assignee,priority,project", expiry=15 * 60)

        # Filter out issues that have already been notified about
        return [issue for issue in all_issues
                if not self.was_issue_notified('issues', issue.get('key'))]
