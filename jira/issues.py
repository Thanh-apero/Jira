import logging
import requests
import json
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class IssueHandler:
    """
    Handles all operations related to Jira issues including searching,
    creating, updating, and retrieving issue details.
    """

    def __init__(self, core):
        """Initialize with a JiraCore instance"""
        self.core = core

    def get_issue_with_changelog(self, issue_key, use_cache=True, fields=None):
        """
        Get issue details including changelog with optimized performance
        optional fields parameter to reduce response size
        """
        cache_key = f"changelog_{issue_key}_{fields or 'all'}"

        # Return from cache if valid and requested
        if use_cache and self.core._is_cache_valid(cache_key) and cache_key in self.core._issues_cache:
            return self.core._issues_cache[cache_key]

        if not self.core.is_configured():
            logger.error("Jira API credentials not configured")
            return None

        try:
            # Build request parameters
            params = {"expand": "changelog"}
            if fields:
                params["fields"] = fields

            response = requests.get(
                f"{self.core.jira_url}/rest/api/2/issue/{issue_key}",
                params=params,
                auth=self.core.auth,
                timeout=10  # Add timeout to prevent hanging
            )

            if response.status_code == 200:
                issue_detail = response.json()

                # Cache the result with shorter expiry for frequently changing issues
                if use_cache:
                    expiry = 900 if fields else 3600  # 15 min for partial, 1 hour for full
                    self.core._set_cache('issues', cache_key, issue_detail, expiry=expiry)

                return issue_detail
            elif response.status_code == 404:
                logger.warning(f"Issue {issue_key} not found")
                return None
            else:
                logger.error(f"Failed to get issue {issue_key}: {response.status_code} - {response.text[:200]}")
                return None
        except requests.exceptions.Timeout:
            logger.error(f"Timeout while fetching issue {issue_key}")
            return None
        except Exception as e:
            logger.error(f"Error getting issue {issue_key}: {str(e)}")
            return None

    def search_issues(self, jql, fields=None, max_results=50, expand=None, use_cache=True, expiry=None):
        """Search for issues using JQL"""
        cache_key = f"jql_{jql}_{fields}_{max_results}_{expand}"

        # Return from cache if valid and not for time-sensitive queries
        if use_cache and not ('updated >=' in jql or 'created >=' in jql) and self.core._is_cache_valid(
                cache_key) and cache_key in self.core._issues_cache:
            logger.info(f"Using cached issues data for query {jql[:30]}...")
            return self.core._issues_cache[cache_key]

        if not self.core.is_configured():
            logger.error("Jira API credentials not configured")
            return []

        if fields is None:
            fields = "key,summary,issuetype,creator,priority,created,project,status,comment,duedate,assignee"

        try:
            logger.info(f"Searching issues with JQL: {jql[:50]}...")

            # Add pagination to support more than 50 issues
            all_issues = []
            start_at = 0

            while True:
                params = {
                    "jql": jql,
                    "fields": fields,
                    "maxResults": 100,  # Get 100 at a time (Jira's recommended page size)
                    "startAt": start_at
                }

                if expand:
                    params["expand"] = expand

                response = requests.get(
                    f"{self.core.jira_url}/rest/api/2/search",
                    params=params,
                    auth=self.core.auth
                )

                if response.status_code == 200:
                    data = response.json()
                    issues = data.get('issues', [])
                    all_issues.extend(issues)

                    # Check if we've reached the end or the max limit
                    if len(issues) == 0 or len(all_issues) >= max_results or start_at + len(issues) >= data.get('total',
                                                                                                                0):
                        break

                    # Move to next page
                    start_at += len(issues)
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

            # Limit to max_results
            if len(all_issues) > max_results:
                all_issues = all_issues[:max_results]

            # Only cache if not a time-sensitive query
            if use_cache and not ('updated >=' in jql or 'created >=' in jql):
                self.core._set_cache('issues', cache_key, all_issues, expiry)

            return all_issues

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
                if not self.core.was_issue_notified('issues', issue.get('key'))]

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
            fields="key,summary,status,assignee,updated,project",
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
                history_created = history.get('created')
                change_key = f"{issue_key}-{history_id}"

                # Skip if already notified about this change
                if self.core.was_issue_notified('status_changes', change_key):
                    continue

                # Only process changes that are within the time window
                if history_created:
                    try:
                        change_time = datetime.fromisoformat(history_created.replace('Z', '+00:00'))
                        now = datetime.now(change_time.tzinfo)
                        if (now - change_time).total_seconds() / 3600 > hours:
                            continue
                    except:
                        pass  # If we can't parse the time, still process the change

                for item in history.get('items', []):
                    if item.get('field') == 'status':
                        # Only include if changing to Todo or In Progress
                        to_status = item.get('toString', '').lower()
                        if to_status in ['to do', 'todo', 'in progress']:
                            # Make sure we have the latest assignee information
                            if not issue.get('fields', {}).get('assignee'):
                                # If assignee info is missing, try to get it from the full issue details
                                detailed_issue = self.get_issue_details(issue_key)
                                if detailed_issue and detailed_issue.get('fields', {}).get('assignee'):
                                    issue['fields']['assignee'] = detailed_issue['fields']['assignee']

                            # Add the history to the issue object for processing
                            if 'status_changes' not in issue:
                                issue['status_changes'] = []
                            issue['status_changes'].append({
                                'history_id': history_id,
                                'from_status': item.get('fromString'),
                                'to_status': item.get('toString'),
                                'updated_by': history.get('author', {}).get('displayName')
                            })

                            # Only add the issue once if it has valid status changes
                            if issue not in issues_with_changes:
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
                if self.core.was_issue_notified('comments', f"{issue_key}-{comment_id}"):
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
                if not self.core.was_issue_notified('issues', issue.get('key'))]

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
                if not self.core.was_issue_notified('issues', issue.get('key'))]

    def create_issue(self, project_key, issue_data):
        """Create an issue in Jira."""
        if not self.core.is_configured():
            logger.error("Jira API not configured. Cannot create issue.")
            return {"error": True, "message": "Jira API not configured."}

        try:
            # The payload for creating an issue typically involves a "fields" object
            payload = {
                "fields": {
                    "project": {
                        "key": project_key
                    },
                    # Unpack other issue_data directly into fields
                    **issue_data
                }
            }

            # Ensure issuetype is an object if it's a string (e.g. "Task")
            # Some Jira instances expect {"name": "Task"} or {"id": "10001"}
            if "issuetype" in payload["fields"] and isinstance(payload["fields"]["issuetype"], str):
                payload["fields"]["issuetype"] = {"name": payload["fields"]["issuetype"]}

            # Ensure priority is an object if it's a string
            if "priority" in payload["fields"] and isinstance(payload["fields"]["priority"], str):
                payload["fields"]["priority"] = {"name": payload["fields"]["priority"]}

            logger.info(f"Attempting to create issue in project {project_key} with payload: {json.dumps(payload)}")

            response = requests.post(
                f"{self.core.jira_url}/rest/api/2/issue",
                json=payload,
                auth=self.core.auth,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code == 201:  # 201 Created is success
                created_issue = response.json()
                logger.info(f"Successfully created issue {created_issue.get('key')} in project {project_key}")
                return {"key": created_issue.get('key'), "self": created_issue.get('self'), "error": False}
            else:
                error_message = f"Failed to create issue. Status: {response.status_code}"
                details = {}
                try:
                    details = response.json()
                    if 'errorMessages' in details and details['errorMessages']:
                        error_message += f" - Errors: {', '.join(details['errorMessages'])}"
                    if 'errors' in details and details['errors']:
                        field_errors = []
                        for field, msg in details['errors'].items():
                            field_errors.append(f"{field}: {msg}")
                        error_message += f" - Field Errors: {'; '.join(field_errors)}"

                except ValueError:  # Not a JSON response
                    error_message += f" - Response: {response.text[:500]}"  # Log first 500 chars

                logger.error(error_message)
                logger.error(
                    f"Full Jira response for create_issue error: {response.text}")  # Log full response for debugging
                return {"error": True, "message": error_message, "details": details,
                        "status_code": response.status_code}

        except requests.exceptions.RequestException as e:
            logger.error(f"RequestException creating issue: {str(e)}")
            return {"error": True, "message": f"Network error creating issue: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error creating issue: {str(e)}")
            return {"error": True, "message": f"Unexpected server error creating issue: {str(e)}"}

    def update_issue(self, issue_key, update_data):
        """Update an existing issue"""
        if not self.core.is_configured():
            logger.error("Jira API not configured. Cannot update issue.")
            return {"error": True, "message": "Jira API not configured."}

        try:
            # Build payload for the update
            payload = {
                "fields": update_data
            }

            # Ensure certain fields are properly formatted as objects
            if "priority" in update_data and isinstance(update_data["priority"], str):
                payload["fields"]["priority"] = {"name": update_data["priority"]}

            # Handle fix versions
            if "fix_version" in update_data:
                if update_data["fix_version"]:
                    payload["fields"]["fixVersions"] = [{"id": update_data["fix_version"]}]
                else:
                    payload["fields"]["fixVersions"] = []
                # Remove the original key as it's not a direct field
                del payload["fields"]["fix_version"]

            logger.info(f"Updating issue {issue_key} with data: {json.dumps(payload)}")

            response = requests.put(
                f"{self.core.jira_url}/rest/api/2/issue/{issue_key}",
                json=payload,
                auth=self.core.auth,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code in (200, 204):
                logger.info(f"Successfully updated issue {issue_key}")

                # Handle sprint separately as it uses a different API
                if "sprint_id" in update_data and update_data["sprint_id"]:
                    from jira.sprints import SprintHandler
                    sprint_handler = SprintHandler(self.core)
                    sprint_result = sprint_handler.add_issue_to_sprint(update_data["sprint_id"], issue_key)
                    if not sprint_result:
                        logger.warning(f"Failed to update sprint for issue {issue_key}")
                        return {"error": False, "warning": "Issue updated but sprint assignment failed"}

                return {"error": False}
            else:
                error_message = f"Failed to update issue. Status: {response.status_code}"
                try:
                    if response.text:
                        error_data = response.json()
                        if 'errorMessages' in error_data:
                            error_message += f": {error_data['errorMessages']}"
                        if 'errors' in error_data:
                            field_errors = []
                            for field, msg in error_data['errors'].items():
                                field_errors.append(f"{field}: {msg}")
                            error_message += f" - Field errors: {'; '.join(field_errors)}"
                except:
                    error_message += f": {response.text[:500]}"

                logger.error(error_message)
                return {"error": True, "message": error_message}

        except Exception as e:
            logger.error(f"Error updating issue {issue_key}: {str(e)}")
            return {"error": True, "message": f"Error updating issue: {str(e)}"}

    def get_issue_details(self, issue_key):
        """Get detailed information about a specific issue"""
        # This is a simple wrapper around get_issue_with_changelog but without the changelog
        return self.get_issue_with_changelog(issue_key, use_cache=True, fields=None)

    def find_epic_by_name(self, project_key, epic_name):
        """Find an Epic by its name within a project."""
        if not self.core.is_configured():
            logger.error("Jira API not configured. Cannot find Epic.")
            return None

        try:
            # Search for epics by summary field instead of customfield
            jql = f'project = "{project_key}" AND issuetype = Epic AND summary ~ "{epic_name}"'
            logger.info(f"Searching for Epic with JQL: {jql}")

            response = requests.get(
                f"{self.core.jira_url}/rest/api/2/search",
                params={"jql": jql, "fields": "key,summary", "maxResults": 1},
                auth=self.core.auth
            )
            response.raise_for_status()
            results = response.json()
            issues = results.get('issues', [])

            if issues:
                epic_issue = issues[0]
                epic_key = epic_issue.get('key')
                # Get Epic name from summary field
                actual_epic_name = epic_issue.get('fields', {}).get('summary')
                logger.info(f"Found Epic: Key={epic_key}, Name='{actual_epic_name}'")
                return {"key": epic_key, "summary": actual_epic_name}
            else:
                logger.info(f"No Epic found with name containing '{epic_name}' in project '{project_key}'.")
                return None
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error finding Epic by name '{epic_name}': {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Error finding Epic by name '{epic_name}' in project '{project_key}': {str(e)}")
            return None
