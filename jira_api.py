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

    def get_issue_types(self):
        """Get all available issue types from Jira"""
        if not self.is_configured():
            logger.error("Jira API credentials not configured")
            return []

        try:
            response = requests.get(
                f"{self.jira_url}/rest/api/2/issuetype",
                auth=self.auth
            )

            if response.status_code == 200:
                issue_types = response.json()
                logger.info(f"Successfully fetched {len(issue_types)} issue types from Jira")
                return issue_types
            else:
                logger.error(f"Failed to fetch issue types: {response.status_code}")
                logger.error(f"Response: {response.text}")
                return []
        except Exception as e:
            logger.error(f"Error getting issue types: {str(e)}")
            return []

    def get_available_statuses(self):
        """Get all available statuses from Jira"""
        if not self.is_configured():
            logger.error("Jira API credentials not configured")
            return []

        try:
            response = requests.get(
                f"{self.jira_url}/rest/api/2/status",
                auth=self.auth
            )

            if response.status_code == 200:
                all_statuses = response.json()
                # Process statuses to simplify
                simplified = []
                for status in all_statuses:
                    simplified.append({
                        "id": status.get("id"),
                        "name": status.get("name"),
                        "description": status.get("description"),
                        "category": status.get("statusCategory", {}).get("name") if "statusCategory" in status else None
                    })
                logger.info(f"Found {len(simplified)} statuses in Jira")
                return simplified
            else:
                logger.error(f"Failed to fetch statuses: {response.status_code} {response.text}")
                return []
        except Exception as e:
            logger.error(f"Error fetching statuses: {str(e)}")
            return []

    def test_get_status_transitions(self, project_key, limit=10):
        """
        Test function to get actual status transitions from a project's bugs
        This helps identify the real status names and flow in your Jira instance
        """
        if not self.is_configured():
            logger.error("Jira API credentials not configured")
            return {}

        try:
            # Get bugs in the project
            jql = f"project = {project_key} AND issuetype = Bug ORDER BY updated DESC"
            bugs = self.search_issues(
                jql,
                fields="key,summary,status",
                max_results=limit,
                use_cache=False
            )

            if not bugs:
                logger.info(f"No bugs found in project {project_key}")
                return {}

            # Get all available statuses
            all_statuses = self.get_available_statuses()
            status_names = {status["id"]: status["name"] for status in all_statuses}

            # Store transitions we find
            transitions = {}
            transitions_count = 0

            # For each bug, analyze status changes
            for bug in bugs:
                issue_key = bug.get('key')
                current_status = bug.get('fields', {}).get('status', {}).get('name', 'Unknown')

                # Get issue with changelog
                issue_detail = self.get_issue_with_changelog(issue_key)
                if not issue_detail:
                    continue

                changelog = issue_detail.get('changelog', {}).get('histories', [])

                logger.info(f"Analyzing status transitions for bug {issue_key} (current: {current_status})")

                # Process status changes
                for history in changelog:
                    for item in history.get('items', []):
                        if item.get('field') == 'status':
                            from_status = item.get('fromString', '(unknown)')
                            to_status = item.get('toString', '(unknown)')

                            # Log this transition
                            transition_key = f"{from_status} → {to_status}"
                            if transition_key not in transitions:
                                transitions[transition_key] = 0
                            transitions[transition_key] += 1
                            transitions_count += 1

                            logger.info(f"  {issue_key}: {from_status} → {to_status}")

            logger.info(f"Found {transitions_count} status transitions across {len(bugs)} bugs")
            # Sort transitions by frequency
            sorted_transitions = sorted(
                [(k, v) for k, v in transitions.items()],
                key=lambda x: x[1],
                reverse=True
            )

            # Determine what transitions might indicate a reopening
            reopen_candidates = []
            for transition, count in sorted_transitions:
                from_status, to_status = transition.split(' → ')
                # Look for patterns that might indicate reopening
                if "review" in from_status.lower() and (
                        "open" in to_status.lower() or
                        "progress" in to_status.lower() or
                        "todo" in to_status.lower() or
                        "to do" in to_status.lower()
                ):
                    reopen_candidates.append((transition, count))

            result = {
                "all_statuses": [status["name"] for status in all_statuses],
                "transitions_found": sorted_transitions,
                "possible_reopen_transitions": reopen_candidates
            }

            return result

        except Exception as e:
            logger.error(f"Error testing status transitions: {str(e)}")
            return {}

    def find_reopened_bugs_by_jql(self, project_key, start_date=None, end_date=None, participant=None):
        """
        Find reopened bugs in a project using JQL.
        This function identifies bugs that have been reopened by looking at their status history.
        """
        if not self.is_configured():
            logger.error("Jira API credentials not configured")
            return []

        try:
            # First, get all bugs in the project
            jql_parts = [
                f"project = {project_key}",
                "issuetype = Bug"
            ]

            # Add time constraints if provided
            if start_date:
                jql_parts.append(f'updated >= "{start_date}"')
            if end_date:
                jql_parts.append(f'updated <= "{end_date}"')

            # Add participant filter if provided (assignee only as requested)
            if participant:
                jql_parts.append(f'assignee = "{participant}"')

            jql = " AND ".join(jql_parts)

            logger.info(f"Getting all bugs with JQL: {jql}")

            # Get up to 500 bugs from the project
            all_bugs = self.search_issues(
                jql,
                fields="key,summary,status,assignee,reporter,issuetype,priority,created,updated",
                max_results=500,
                use_cache=False  # Don't cache bug searches
            )

            if not all_bugs:
                logger.info(f"No bugs found in project {project_key}")
                return []

            logger.info(f"Found {len(all_bugs)} bugs in project {project_key}")

            # For each bug, check its changelog to see if it was reopened
            reopened_bugs = []

            # CUSTOMIZATION: Define what statuses indicate "reviewing" and what statuses indicate "earlier states"
            # These will be used to detect reopened bugs
            reviewing_statuses = ['reviewing', 'review', 'in review', 'under review', 'resolved', 'done', 'closed',
                                  'completed', 'fix committed', 'verified']
            earlier_statuses = ['open', 'in progress', 'reopened', 'to do', 'todo', 'new', 'backlog',
                                'selected for development']

            for bug in all_bugs:
                issue_key = bug.get('key')

                try:
                    # Get the full issue with changelog
                    issue_detail = self.get_issue_with_changelog(issue_key)
                    if not issue_detail:
                        continue

                    changelog = issue_detail.get('changelog', {}).get('histories', [])

                    # Look for status changes that indicate a reopen
                    was_reopened = False
                    reopen_time = None
                    from_status_value = ""
                    to_status_value = ""

                    for history in changelog:
                        for item in history.get('items', []):
                            if item.get('field') == 'status':
                                from_status = item.get('fromString', '').lower()
                                to_status = item.get('toString', '').lower()

                                # Check if this transition matches our definition of "reopened"
                                # That is, moving from a reviewing status back to an earlier status
                                if any(review_status in from_status for review_status in reviewing_statuses) and \
                                        any(early_status in to_status for early_status in earlier_statuses):
                                    was_reopened = True
                                    reopen_time = history.get('created')
                                    from_status_value = item.get('fromString', '')
                                    to_status_value = item.get('toString', '')
                                    logger.info(f"Found reopened bug {issue_key}: {from_status} → {to_status}")
                                    break

                        if was_reopened:
                            break

                    if was_reopened:
                        bug['was_reopened'] = True
                        bug['reopen_time'] = reopen_time
                        bug['reopen_from'] = from_status_value
                        bug['reopen_to'] = to_status_value
                        reopened_bugs.append(bug)

                except Exception as e:
                    logger.error(f"Error checking bug {issue_key}: {str(e)}")

            logger.info(f"Found {len(reopened_bugs)} reopened bugs out of {len(all_bugs)} bugs")
            return reopened_bugs

        except Exception as e:
            logger.error(f"Error searching for reopened bugs: {str(e)}")
            return []

    def find_reopened_bugs(self, project_keys):
        """
        Find bugs that have been reopened across multiple projects
        """
        if not isinstance(project_keys, list):
            project_keys = [project_keys]

        all_reopened_bugs = []
        for project_key in project_keys:
            logger.info(f"Checking project {project_key} for reopened bugs")
            project_reopened_bugs = self.find_reopened_bugs_by_jql(project_key)
            all_reopened_bugs.extend(project_reopened_bugs)

        logger.info(f"Total reopened bugs across all projects: {len(all_reopened_bugs)}")
        return all_reopened_bugs

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

    def get_field_id_by_name(self, field_name_to_find):
        """Get the ID of a Jira field by its name."""
        if not self.is_configured():
            logger.error("Jira API not configured. Cannot get field ID.")
            return None
        try:
            logger.info(f"Fetching all fields to find ID for '{field_name_to_find}'")
            response = requests.get(
                f"{self.jira_url}/rest/api/2/field",  # Using API v2 as per existing code
                auth=self.auth
            )
            response.raise_for_status()  # Raise an exception for HTTP errors
            all_fields = response.json()

            for field in all_fields:
                if field.get('name', '').lower() == field_name_to_find.lower():
                    logger.info(f"Found field '{field_name_to_find}' with ID: {field['id']}")
                    return field['id']

            logger.warning(f"Field with name '{field_name_to_find}' not found in Jira.")
            return None
        except requests.exceptions.HTTPError as e:
            logger.error(
                f"HTTP error getting field ID for '{field_name_to_find}': {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Error getting field ID for '{field_name_to_find}': {str(e)}")
            return None

    def find_custom_fields(self):
        """Find all custom fields and their details to identify start_date and story_point fields"""
        if not self.is_configured():
            logger.error("Jira API not configured. Cannot find custom fields.")
            return None

        try:
            logger.info("Fetching all fields to find custom fields")
            response = requests.get(
                f"{self.jira_url}/rest/api/2/field",
                auth=self.auth
            )
            response.raise_for_status()
            all_fields = response.json()

            # Filter for custom fields and fields that might be related to dates or points
            custom_fields = []
            date_fields = []
            point_fields = []

            for field in all_fields:
                field_id = field.get('id', '')
                field_name = field.get('name', '').lower()

                # Log all fields for debugging
                logger.info(f"Field: {field_name}, ID: {field_id}, Type: {field.get('schema', {}).get('type')}")

                if field_id.startswith('customfield_'):
                    custom_fields.append(field)

                    # Look for date-related fields
                    if any(term in field_name for term in ['start', 'begin', 'date', 'scheduled']):
                        date_fields.append(field)

                    # Look for story point related fields
                    if any(term in field_name for term in ['point', 'story', 'sp', 'estimate', 'effort']):
                        point_fields.append(field)

            logger.info(f"Found {len(custom_fields)} custom fields")
            logger.info(f"Found {len(date_fields)} date-related fields: {[f['name'] for f in date_fields]}")
            logger.info(f"Found {len(point_fields)} point-related fields: {[f['name'] for f in point_fields]}")

            return {
                'all_custom_fields': custom_fields,
                'date_fields': date_fields,
                'point_fields': point_fields
            }

        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error getting custom fields: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Error getting custom fields: {str(e)}")
            return None

    def find_epic_by_name(self, project_key, epic_name):
        """Find an Epic by its name within a project."""
        if not self.is_configured():
            logger.error("Jira API not configured. Cannot find Epic.")
            return None

        try:
            # Search for epics by summary field instead of customfield
            jql = f'project = "{project_key}" AND issuetype = Epic AND summary ~ "{epic_name}"'
            logger.info(f"Searching for Epic with JQL: {jql}")

            response = requests.get(
                f"{self.jira_url}/rest/api/2/search",
                params={"jql": jql, "fields": "key,summary", "maxResults": 1},
                auth=self.auth
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

    def get_project_versions(self, project_key):
        """Get all versions for a project"""
        if not self.is_configured():
            logger.error("Jira API not configured. Cannot get project versions.")
            return []

        cache_key = f"versions_{project_key}"

        # Return from cache if valid
        if self._is_cache_valid(cache_key) and cache_key in self._projects_cache:
            logger.info(f"Using cached versions for project {project_key}")
            return self._projects_cache[cache_key]

        try:
            logger.info(f"Fetching versions for project {project_key}")
            response = requests.get(
                f"{self.jira_url}/rest/api/2/project/{project_key}/versions",
                auth=self.auth
            )

            if response.status_code == 200:
                versions = response.json()
                logger.info(f"Found {len(versions)} versions for project {project_key}")

                # Sort versions by release date/sequence if available
                versions.sort(key=lambda v: v.get('releaseDate', ''), reverse=True)

                # Cache the result for 15 minutes
                self._set_cache('projects', cache_key, versions, expiry=15 * 60)
                return versions
            else:
                logger.error(f"Failed to fetch versions: {response.status_code} - {response.text}")
                return []
        except Exception as e:
            logger.error(f"Error getting versions for project {project_key}: {str(e)}")
            return []

    def get_issues_by_version(self, project_key, version_id):
        """Get issues for a specific version"""
        if not self.is_configured():
            logger.error("Jira API not configured. Cannot get version issues.")
            return []

        try:
            jql = f'project = {project_key} AND fixVersion = {version_id}'

            issues = self.search_issues(
                jql,
                fields="key,summary,status,assignee,issuetype,priority,duedate",
                max_results=1000,
                use_cache=False  # Always get fresh data for version issues
            )

            logger.info(f"Found {len(issues)} issues for version {version_id} in project {project_key}")
            return issues
        except Exception as e:
            logger.error(f"Error getting issues for version {version_id}: {str(e)}")
            return []

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
                    params={"state": "active,future"},  # Get both active and future sprints
                    auth=self.auth
                )

                if sprints_response.status_code == 200:
                    sprints = sprints_response.json().get('values', [])
                    # Add board info to each sprint
                    for sprint in sprints:
                        sprint['boardId'] = board_id
                        sprint['boardName'] = board.get('name', '')
                    active_sprints.extend(sprints)

            logger.info(f"Found {len(active_sprints)} active/future sprints for project {project_key}")

            # Cache for a shorter time (5 minutes)
            self._set_cache('sprints', cache_key, active_sprints, 5 * 60)
            return active_sprints

        except Exception as e:
            logger.error(f"Error getting active sprints: {str(e)}")
            return []

    def add_issue_to_sprint(self, sprint_id, issue_key):
        """Add an issue to a sprint"""
        if not self.is_configured():
            logger.error("Jira API credentials not configured")
            return False

        try:
            logger.info(f"Adding issue {issue_key} to sprint {sprint_id}")

            response = requests.post(
                f"{self.jira_url}/rest/agile/1.0/sprint/{sprint_id}/issue",
                json={"issues": [issue_key]},
                auth=self.auth
            )

            if response.status_code in (201, 204):
                logger.info(f"Successfully added issue {issue_key} to sprint {sprint_id}")
                return True
            else:
                logger.error(f"Failed to add issue to sprint: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error adding issue to sprint: {str(e)}")
            return False

    def get_project_statistics(self, project_key, start_date=None, end_date=None, participant=None):
        """
        Get project statistics including total issues, status breakdown, etc.
        """
        if not self.is_configured():
            logger.error("Jira API credentials not configured")
            return {}

        # Check cache first for quick response
        cache_key = f"stats_{project_key}_{start_date}_{end_date}_{participant}"
        if self._is_cache_valid(cache_key) and cache_key in self._projects_cache:
            logger.info(f"Using cached statistics for project {project_key}")
            return self._projects_cache[cache_key]

        try:
            # Base JQL to get all issues in the project
            jql_parts = [f"project = {project_key}"]

            # Add time constraints if provided
            if start_date:
                jql_parts.append(f'updated >= "{start_date}"')
            if end_date:
                jql_parts.append(f'updated <= "{end_date}"')

            # Add participant filter if provided
            if participant:
                # Only filter by assignee as requested
                jql_parts.append(f'assignee = "{participant}"')

            jql = " AND ".join(jql_parts)

            # OPTIMIZATION: Get all issues in a single query with all needed fields
            # This reduces the number of API calls significantly
            all_issues = self.search_issues(
                jql,
                fields="key,summary,status,assignee,reporter,issuetype,priority,created,updated,comment",
                max_results=500,  # Reasonable limit for statistics
                use_cache=True,  # Use cache when possible
                expiry=300  # Cache for 5 minutes
            )

            # Count issues by status and type
            status_counts = {}
            issue_types = {}
            completed_tasks_count = 0
            bugs_count = 0
            recent_issues = []

            # Process all issues in a single pass (no additional API calls)
            for issue in all_issues:
                fields = issue.get('fields', {})

                # Get status and count
                status = fields.get('status', {}).get('name', 'Unknown')
                if status in status_counts:
                    status_counts[status] += 1
                else:
                    status_counts[status] = 1

                # Check if completed
                if status.lower() in ['done', 'closed', 'resolved', 'completed']:
                    completed_tasks_count += 1

                # Get issue type and count
                issue_type = fields.get('issuetype', {}).get('name', 'Unknown')
                if issue_type in issue_types:
                    issue_types[issue_type] += 1
                else:
                    issue_types[issue_type] = 1

                # Count bugs
                if issue_type.lower() == 'bug':
                    bugs_count += 1

                # Add to recent issues list
                recent_issues.append({
                    'key': issue.get('key'),
                    'summary': fields.get('summary', 'No summary'),
                    'status': status,
                    'type': issue_type,
                    'assignee': fields.get('assignee', {}).get('displayName') if fields.get('assignee') else None,
                    'updated': fields.get('updated')
                })

            # Sort and limit recent issues
            recent_issues.sort(key=lambda x: x.get('updated', ''), reverse=True)
            recent_issues = recent_issues[:50]  # Limit to most recent 50

            # OPTIMIZATION: Get participants with caching
            # We don't need to recalculate this for every statistics request
            participants = self.get_project_participants(project_key)

            # OPTIMIZATION: For reopened bugs - use efficient detection and caching
            # Only look at bugs, and cache the result
            reopened_bugs_cache_key = f"reopened_bugs_{project_key}_{start_date}_{end_date}_{participant}"

            if self._is_cache_valid(reopened_bugs_cache_key) and reopened_bugs_cache_key in self._issues_cache:
                reopened_bugs = self._issues_cache[reopened_bugs_cache_key]
                logger.info(f"Using cached reopened bugs for project {project_key}")
            else:
                # Get reopened bugs (filtered to bugs only to reduce API calls)
                reopened_bugs = self.find_reopened_bugs_by_jql(
                    project_key,
                    start_date=start_date,
                    end_date=end_date,
                    participant=participant
                )
                # Cache reopened bugs result for 5 minutes
                self._set_cache('issues', reopened_bugs_cache_key, reopened_bugs, expiry=300)

            reopened_bugs_count = len(reopened_bugs)

            # NEW: Gather statistics about who reopened bugs
            reopener_stats = {}
            for bug in reopened_bugs:
                reopener = bug.get('reopen_by', 'Unknown')
                if reopener in reopener_stats:
                    reopener_stats[reopener] += 1
                else:
                    reopener_stats[reopener] = 1

            # Sort reopeners by number of reopens (most first)
            sorted_reopeners = sorted(
                [(name, count) for name, count in reopener_stats.items()],
                key=lambda x: x[1],
                reverse=True
            )

            # NEW: Gather statistics about bugs by assignee
            assignee_bug_stats = {}
            for bug in all_issues:
                if bug.get('fields', {}).get('issuetype', {}).get('name', '').lower() == 'bug':
                    assignee = bug.get('fields', {}).get('assignee', {}).get('displayName', 'Unassigned')
                    if assignee in assignee_bug_stats:
                        assignee_bug_stats[assignee]['total'] += 1
                    else:
                        assignee_bug_stats[assignee] = {'total': 1, 'reopened': 0}

            # Add reopened bugs to assignee stats
            for bug in reopened_bugs:
                assignee = bug.get('fields', {}).get('assignee', {}).get('displayName', 'Unassigned')
                if assignee in assignee_bug_stats:
                    assignee_bug_stats[assignee]['reopened'] += 1
                else:
                    assignee_bug_stats[assignee] = {'total': 1, 'reopened': 1}

            # Sort assignees by total bugs (most first)
            sorted_assignees = sorted(
                [(name, stats) for name, stats in assignee_bug_stats.items()],
                key=lambda x: x[1]['total'],
                reverse=True
            )

            # Build statistics response
            statistics = {
                'total_issues': len(all_issues),
                'completed_tasks_count': completed_tasks_count,
                'bugs_count': bugs_count,
                'reopened_bugs_count': reopened_bugs_count,
                'status_counts': status_counts,
                'issue_types': issue_types,
                'recent_issues': recent_issues,
                'participants': participants,
                'total_participants': len(participants),
                # New statistics
                'reopeners': sorted_reopeners,
                'assignee_bug_stats': sorted_assignees
            }

            # Cache the whole statistics result for 2 minutes
            self._set_cache('projects', cache_key, statistics, expiry=120)

            logger.info(f"Generated statistics for project {project_key}: {bugs_count} bugs, {reopened_bugs_count} reopened bugs")
            return statistics

        except Exception as e:
            logger.error(f"Error generating project statistics: {str(e)}")
            return {}

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
                    f"{self.jira_url}/rest/api/2/search",
                    params=params,
                    auth=self.auth
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
                self._set_cache('issues', cache_key, all_issues, expiry)

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
                if self.was_issue_notified('status_changes', change_key):
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

    def get_issue_with_changelog(self, issue_key, use_cache=True, fields=None):
        """
        Get issue details including changelog with optimized performance
        optional fields parameter to reduce response size
        """
        cache_key = f"changelog_{issue_key}_{fields or 'all'}"

        # Return from cache if valid and requested
        if use_cache and self._is_cache_valid(cache_key) and cache_key in self._issues_cache:
            return self._issues_cache[cache_key]

        if not self.is_configured():
            logger.error("Jira API credentials not configured")
            return None

        try:
            # Build request parameters
            params = {"expand": "changelog"}
            if fields:
                params["fields"] = fields

            response = requests.get(
                f"{self.jira_url}/rest/api/2/issue/{issue_key}",
                params=params,
                auth=self.auth,
                timeout=10  # Add timeout to prevent hanging
            )

            if response.status_code == 200:
                issue_detail = response.json()

                # Cache the result with shorter expiry for frequently changing issues
                if use_cache:
                    expiry = 900 if fields else 3600  # 15 min for partial, 1 hour for full
                    self._set_cache('issues', cache_key, issue_detail, expiry=expiry)

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

    def get_project_participants(self, project_key):
        """
        Get all participants (users who have been assigned to issues) in a project
        """
        if not self.is_configured():
            logger.error("Jira API credentials not configured")
            return []

        cache_key = f"participants_{project_key}"

        # Return from cache if valid
        if self._is_cache_valid(cache_key) and cache_key in self._projects_cache:
            logger.info(f"Using cached participants data for project {project_key}")
            return self._projects_cache[cache_key]

        try:
            # OPTIMIZATION: Use a more efficient query with just the fields we need
            # Also limit to recent issues to improve performance
            jql = f'project = {project_key} ORDER BY updated DESC'
            issues = self.search_issues(
                jql,
                fields="assignee",  # Only request the assignee field
                max_results=200,  # Reduced from 500 to 200
                use_cache=True,  # Use cache to avoid repeated calls
                expiry=1800  # Cache for 30 minutes
            )

            participants = {}

            # Process assignees only
            for issue in issues:
                fields = issue.get('fields', {})

                # Process assignee
                assignee = fields.get('assignee')
                if assignee and assignee.get('key'):
                    user_key = assignee.get('key')
                    if user_key not in participants:
                        participants[user_key] = {
                            'key': user_key,
                            'name': assignee.get('displayName', 'Unknown'),
                            'avatarUrl': assignee.get('avatarUrls', {}).get('48x48', ''),
                            'email': assignee.get('emailAddress', ''),
                            'issueCount': 0,
                            'assignedCount': 0
                        }
                    participants[user_key]['assignedCount'] += 1
                    participants[user_key]['issueCount'] += 1

            # Convert dictionary to list and sort by issue count
            result = list(participants.values())
            result.sort(key=lambda x: x['issueCount'], reverse=True)

            # Cache the result for a longer time (1 hour) since participants don't change often
            self._set_cache('projects', cache_key, result, expiry=3600)  # Increased from 30 to 60 minutes

            logger.info(f"Found {len(result)} participants (assignees) in project {project_key}")
            return result

        except Exception as e:
            logger.error(f"Error getting project participants: {str(e)}")
            return []

    def find_reopened_bugs_by_jql(self, project_key, start_date=None, end_date=None, participant=None):
        """
        Find reopened bugs in a project using JQL.
        This function identifies bugs that have been reopened by looking at their status history.
        """
        if not self.is_configured():
            logger.error("Jira API credentials not configured")
            return []

        # Check cache for reopened bugs
        cache_key = f"reopen_bugs_{project_key}_{start_date}_{end_date}_{participant}"
        if self._is_cache_valid(cache_key) and cache_key in self._issues_cache:
            logger.info(f"Using cached reopened bugs for project {project_key}")
            return self._issues_cache[cache_key]

        try:
            # First, get all bugs in the project
            jql_parts = [
                f"project = {project_key}",
                "issuetype = Bug"
            ]

            # Add time constraints if provided
            if start_date:
                jql_parts.append(f'updated >= "{start_date}"')
            if end_date:
                jql_parts.append(f'updated <= "{end_date}"')

            # Add participant filter if provided (assignee only as requested)
            if participant:
                jql_parts.append(f'assignee = "{participant}"')

            jql = " AND ".join(jql_parts)

            logger.info(f"Getting bugs with JQL: {jql}")

            # OPTIMIZATION: Get bugs with changelog in a single request
            # This reduces API calls by using the expand parameter
            all_bugs = self.search_issues(
                jql,
                fields="key,summary,status,assignee,reporter,issuetype,priority,created,updated",
                expand="changelog",  # Include changelog directly to avoid separate API calls
                max_results=200,
                use_cache=False
            )

            if not all_bugs:
                logger.info(f"No bugs found in project {project_key}")
                # Cache empty result for a short time
                self._set_cache('issues', cache_key, [], expiry=60)
                return []

            logger.info(f"Found {len(all_bugs)} bugs in project {project_key}, checking for reopens...")

            # For each bug, check its changelog to see if it was reopened
            reopened_bugs = []

            # Define status transition patterns that indicate reopening
            from_states = ["reviewing"]
            to_states = ["todo", "to do", "in progress", "reopened", "request"]

            for bug in all_bugs:
                issue_key = bug.get('key')
                changelog = bug.get('changelog', {}).get('histories', [])  # Get changelog directly from expanded data

                # Look for status changes that indicate a reopen
                was_reopened = False
                reopen_time = None
                from_status_value = ""
                to_status_value = ""
                reopen_by = ""  # Who made the reopen action

                for history in changelog:
                    for item in history.get('items', []):
                        if item.get('field') == 'status':
                            from_status = item.get('fromString', '').lower()
                            to_status = item.get('toString', '').lower()

                            # Check if this is from reviewing to an earlier state
                            # Using the CHANGED FROM ... TO logic as per JIRA JQL syntax
                            if any(review_status in from_status for review_status in from_states) and \
                                    any(early_status in to_status for early_status in to_states):
                                was_reopened = True
                                reopen_time = history.get('created')
                                from_status_value = item.get('fromString', '')
                                to_status_value = item.get('toString', '')

                                # Get who performed the status change (reopen action)
                                if 'author' in history:
                                    reopen_by = history.get('author', {}).get('displayName', 'Unknown')

                                logger.info(
                                    f"Found reopened bug {issue_key}: {from_status} → {to_status} by {reopen_by}")
                                break

                    if was_reopened:
                        break

                if was_reopened:
                    bug['was_reopened'] = True
                    bug['reopen_time'] = reopen_time
                    bug['reopen_from'] = from_status_value
                    bug['reopen_to'] = to_status_value
                    bug['reopen_by'] = reopen_by  # Store who reopened it
                    reopened_bugs.append(bug)

            logger.info(f"Found {len(reopened_bugs)} reopened bugs out of {len(all_bugs)} bugs")

            # Cache the result for 5 minutes
            self._set_cache('issues', cache_key, reopened_bugs, expiry=300)
            return reopened_bugs

        except Exception as e:
            logger.error(f"Error searching for reopened bugs: {str(e)}")
            return []

    def find_reopened_bugs(self, project_keys):
        """
        Find bugs that have been reopened across multiple projects
        """
        if not isinstance(project_keys, list):
            project_keys = [project_keys]

        all_reopened_bugs = []
        for project_key in project_keys:
            logger.info(f"Checking project {project_key} for reopened bugs")
            project_reopened_bugs = self.find_reopened_bugs_by_jql(project_key)
            all_reopened_bugs.extend(project_reopened_bugs)

        logger.info(f"Total reopened bugs across all projects: {len(all_reopened_bugs)}")
        return all_reopened_bugs
