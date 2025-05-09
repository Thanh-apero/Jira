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
                max_results=100,
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

    def create_issue(self, project_key, issue_data):
        """
        Create a new issue in Jira.
        Args:
            project_key (str): The key of the project.
            issue_data (dict): Dictionary with issue details. Expected keys:
                summary (str): Issue summary.
                issuetype (str): Type of issue (e.g., "Task", "Bug", "Epic"). Defaults to "Task".
                priority (str, optional): Name of the priority.
                duedate (str, optional): Due date "YYYY-MM-DD".
                epic (str, optional): Name of the Epic to link or create.
                original_estimate (str, optional): Original estimate (e.g., "2h", "1d").
                start_date (str, optional): Start date "YYYY-MM-DD".
                story_points (float, optional): Story points.
                fix_version (str, optional): Fix version ID.
                sprint_id (str, optional): Sprint ID to add the issue to after creation.
        Returns:
            dict: Jira API response or error dict.
        """
        if not self.is_configured():
            logger.error("Jira API credentials not configured. Cannot create issue.")
            return {"error": True, "message": "Jira API credentials not configured."}

        url = f"{self.jira_url}/rest/api/2/issue"
        issue_type_name = issue_data.get("issuetype", "Task")

        fields = {
            "project": {"key": project_key},
            "summary": issue_data.get("summary", f"New {issue_type_name}"),
            "issuetype": {"name": issue_type_name}
        }

        if issue_data.get("priority"):
            fields["priority"] = {"name": issue_data.get("priority")}
        if issue_data.get("duedate"):
            fields["duedate"] = issue_data.get("duedate")
        if issue_data.get("original_estimate"):
            # Jira's time tracking format might be specific, e.g., "1w 2d 3h 45m"
            # Or it might take seconds. Assuming direct string for now.
            fields["timetracking"] = {"originalEstimate": issue_data.get("original_estimate")}

        if issue_data.get("start_date"):
            fields["customfield_10015"] = issue_data.get("start_date")

        # Special handling for Epic creation or linking
        if issue_type_name.lower() == 'epic':
            # Instead of trying to set customfield_10150 directly, which is causing errors,
            # just use the summary field for the Epic name. This is a common pattern.
            # The Epic Name field is usually auto-populated from summary if not specified.
            # No special handling needed for Epic name in this Jira instance
            pass

        # Handle fixVersion if specified
        if issue_data.get("fix_version"):
            fix_version_id = issue_data.get("fix_version")
            fields["fixVersions"] = [{"id": fix_version_id}]

        # If linking to an Epic (app.py passes epic_link_value)
        elif issue_data.get("epic_link_value"):  # This key comes from app.py
            epic_link_field_id = self.get_field_id_by_name("Epic Link")
            if epic_link_field_id:
                # Check if this field is available on the screen before adding it
                try:
                    # Make a minimal test API call to validate if we can set this field
                    test_response = requests.get(
                        f"{self.jira_url}/rest/api/2/field/{epic_link_field_id}",
                        auth=self.auth
                    )
                    if test_response.status_code == 200:
                        fields[epic_link_field_id] = issue_data["epic_link_value"]  # Expects Epic Key
                    else:
                        logger.warning(
                            f"Epic Link field {epic_link_field_id} is not accessible. Task will not be linked to Epic.")
                except Exception as e:
                    logger.warning(f"Error checking Epic Link field: {str(e)}. Task will not be linked to Epic.")
            else:
                logger.warning("Could not find 'Epic Link' field ID. Task will not be linked to Epic.")

        payload = {"fields": fields}

        try:
            logger.info(f"Attempting to create issue in project {project_key} with payload: {json.dumps(payload)}")
            response = requests.post(
                url,
                json=payload,
                auth=self.auth,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code == 201:  # 201 Created
                created_issue = response.json()
                issue_key = created_issue.get('key')
                logger.info(f"Successfully created issue {issue_key} in project {project_key}")

                # If sprint_id is provided, add the issue to that sprint
                if issue_data.get("sprint_id"):
                    sprint_id = issue_data.get("sprint_id")
                    sprint_result = self.add_issue_to_sprint(sprint_id, issue_key)
                    if not sprint_result:
                        logger.warning(f"Failed to add issue {issue_key} to sprint {sprint_id}")

                return {"key": issue_key, "id": created_issue.get('id'),
                        "self": created_issue.get('self'), "error": False}
        except requests.exceptions.RequestException as e:
            logger.error(f"Network/Request error creating issue in {project_key}: {str(e)}")
            return {"error": True, "message": f"RequestException: {str(e)}"}
        except Exception as e:  # Catch any other unexpected errors
            logger.error(f"An unexpected error occurred while creating issue in {project_key}: {str(e)}")
            return {"error": True, "message": f"Unexpected error: {str(e)}"}

    def update_issue(self, issue_key, update_data):
        """
        Update an existing issue in Jira.
        Args:
            issue_key (str): The key of the issue to update (e.g., 'PROJECT-123').
            update_data (dict): Dictionary with updated issue details. Same fields as create_issue.
        Returns:
            dict: Status of the update operation.
        """
        if not self.is_configured():
            logger.error("Jira API credentials not configured. Cannot update issue.")
            return {"error": True, "message": "Jira API credentials not configured."}

        url = f"{self.jira_url}/rest/api/2/issue/{issue_key}"

        # Prepare fields to update
        fields = {}

        # Basic fields
        if update_data.get("summary"):
            fields["summary"] = update_data.get("summary")

        if update_data.get("description"):
            fields["description"] = update_data.get("description")

        if update_data.get("priority"):
            fields["priority"] = {"name": update_data.get("priority")}

        if update_data.get("duedate"):
            fields["duedate"] = update_data.get("duedate")

        if update_data.get("original_estimate"):
            fields["timetracking"] = {"originalEstimate": update_data.get("original_estimate")}

        if update_data.get("start_date"):
            fields["customfield_10015"] = update_data.get("start_date")

        if update_data.get("fix_version"):
            fields["fixVersions"] = [{"id": update_data.get("fix_version")}]

        # Only proceed if we have fields to update
        if not fields:
            logger.warning(f"No fields to update for issue {issue_key}")
            return {"error": True, "message": "No fields specified to update."}

        payload = {"fields": fields}

        try:
            logger.info(f"Attempting to update issue {issue_key} with payload: {json.dumps(payload)}")
            response = requests.put(
                url,
                json=payload,
                auth=self.auth,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code == 204:  # 204 No Content is success for updates
                logger.info(f"Successfully updated issue {issue_key}")

                # Handle sprint update - needs separate call
                if update_data.get("sprint_id"):
                    sprint_id = update_data.get("sprint_id")
                    sprint_result = self.add_issue_to_sprint(sprint_id, issue_key)
                    if not sprint_result:
                        logger.warning(f"Failed to add issue {issue_key} to sprint {sprint_id}")

                return {"error": False, "message": f"Issue {issue_key} updated successfully"}
            else:
                logger.error(
                    f"Failed to update issue {issue_key}. Status: {response.status_code}, Response: {response.text}")
                try:
                    error_details = response.json()
                    return {"error": True, "status_code": response.status_code, "message": error_details}
                except:
                    return {"error": True, "status_code": response.status_code, "message": response.text}
        except requests.exceptions.RequestException as e:
            logger.error(f"Network/Request error updating issue {issue_key}: {str(e)}")
            return {"error": True, "message": f"RequestException: {str(e)}"}
        except Exception as e:
            logger.error(f"An unexpected error occurred while updating issue {issue_key}: {str(e)}")
            return {"error": True, "message": f"Unexpected error: {str(e)}"}

    def get_issue_details(self, issue_key):
        """Get detailed information about a specific issue"""
        if not self.is_configured():
            logger.error("Jira API credentials not configured")
            return None

        try:
            logger.info(f"Fetching details for issue {issue_key}")
            response = requests.get(
                f"{self.jira_url}/rest/api/2/issue/{issue_key}",
                params={
                    "fields": "summary,description,issuetype,priority,status,assignee,duedate,fixVersions,project,sprint,customfield_10015"},
                auth=self.auth
            )

            if response.status_code == 200:
                issue = response.json()
                logger.info(f"Successfully retrieved details for issue {issue_key}")
                return issue
            else:
                logger.error(f"Failed to fetch issue {issue_key}: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"Error getting issue details for {issue_key}: {str(e)}")
            return None

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

        # Get all available issue types
        issue_types = self.get_issue_types()

        # Filter for issue types that might represent bugs - look for names containing "bug" or similar terms
        bug_issue_types = [it['name'] for it in issue_types if
                           any(term in it['name'].lower() for term in ['bug', 'defect', 'error', 'issue', 'problem'])]

        if not bug_issue_types:
            # If no bug-like issue types found, just use "Task" as fallback
            bug_issue_types = ["Task"]
            logger.warning(f"No bug-like issue types found. Using Task as fallback.")

        logger.info(f"Using issue types for bugs: {bug_issue_types}")

        # Create JQL to find bugs
        if len(bug_issue_types) == 1:
            issuetype_clause = f"issuetype = \"{bug_issue_types[0]}\""
        else:
            issuetype_clause = f"issuetype IN ({', '.join([f'\"{bt}\"' for bt in bug_issue_types])})"

        bug_jql = f"{issuetype_clause} AND status in ('To Do', 'In Progress', 'Todo', 'Open') AND project in ({','.join(project_keys)})"

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

    def create_issue(self, project_key, issue_data):
        """
        Create a new issue in Jira.
        Args:
            project_key (str): The key of the project.
            issue_data (dict): Dictionary with issue details. Expected keys:
                summary (str): Issue summary.
                issuetype (str): Type of issue (e.g., "Task", "Bug", "Epic"). Defaults to "Task".
                priority (str, optional): Name of the priority.
                duedate (str, optional): Due date "YYYY-MM-DD".
                epic (str, optional): Name of the Epic to link or create.
                original_estimate (str, optional): Original estimate (e.g., "2h", "1d").
                start_date (str, optional): Start date "YYYY-MM-DD".
                story_points (float, optional): Story points.
                fix_version (str, optional): Fix version ID.
        Returns:
            dict: Jira API response or error dict.
        """
        if not self.is_configured():
            logger.error("Jira API credentials not configured. Cannot create issue.")
            return {"error": True, "message": "Jira API credentials not configured."}

        url = f"{self.jira_url}/rest/api/2/issue"
        issue_type_name = issue_data.get("issuetype", "Task")

        fields = {
            "project": {"key": project_key},
            "summary": issue_data.get("summary", f"New {issue_type_name}"),
            "issuetype": {"name": issue_type_name}
        }

        if issue_data.get("priority"):
            fields["priority"] = {"name": issue_data.get("priority")}
        if issue_data.get("duedate"):
            fields["duedate"] = issue_data.get("duedate")
        if issue_data.get("original_estimate"):
            # Jira's time tracking format might be specific, e.g., "1w 2d 3h 45m"
            # Or it might take seconds. Assuming direct string for now.
            fields["timetracking"] = {"originalEstimate": issue_data.get("original_estimate")}

        if issue_data.get("start_date"):
            fields["customfield_10015"] = issue_data.get("start_date")

        # Special handling for Epic creation or linking
        if issue_type_name.lower() == 'epic':
            # Instead of trying to set customfield_10150 directly, which is causing errors,
            # just use the summary field for the Epic name. This is a common pattern.
            # The Epic Name field is usually auto-populated from summary if not specified.
            # No special handling needed for Epic name in this Jira instance
            pass

        # Handle fixVersion if specified
        if issue_data.get("fix_version"):
            fix_version_id = issue_data.get("fix_version")
            fields["fixVersions"] = [{"id": fix_version_id}]

        # If linking to an Epic (app.py passes epic_link_value)
        elif issue_data.get("epic_link_value"):  # This key comes from app.py
            epic_link_field_id = self.get_field_id_by_name("Epic Link")
            if epic_link_field_id:
                # Check if this field is available on the screen before adding it
                try:
                    # Make a minimal test API call to validate if we can set this field
                    test_response = requests.get(
                        f"{self.jira_url}/rest/api/2/field/{epic_link_field_id}",
                        auth=self.auth
                    )
                    if test_response.status_code == 200:
                        fields[epic_link_field_id] = issue_data["epic_link_value"]  # Expects Epic Key
                    else:
                        logger.warning(
                            f"Epic Link field {epic_link_field_id} is not accessible. Task will not be linked to Epic.")
                except Exception as e:
                    logger.warning(f"Error checking Epic Link field: {str(e)}. Task will not be linked to Epic.")
            else:
                logger.warning("Could not find 'Epic Link' field ID. Task will not be linked to Epic.")

        payload = {"fields": fields}

        try:
            logger.info(f"Attempting to create issue in project {project_key} with payload: {json.dumps(payload)}")
            response = requests.post(
                url,
                json=payload,
                auth=self.auth,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code == 201:  # 201 Created
                created_issue = response.json()
                logger.info(f"Successfully created issue {created_issue.get('key')} in project {project_key}")
                return {"key": created_issue.get('key'), "id": created_issue.get('id'),
                        "self": created_issue.get('self'), "error": False}
            else:
                logger.error(
                    f"Failed to create issue in {project_key}. Status: {response.status_code}, Response: {response.text}")
                try:
                    error_details = response.json()
                    # Log the failing payload for easier debugging
                    logger.error(f"Failing payload for {project_key}: {json.dumps(payload)}")
                    logger.error(f"Error details from Jira: {error_details}")
                    return {"error": True, "status_code": response.status_code, "message": error_details,
                            "payload_sent": payload}
                except ValueError:
                    return {"error": True, "status_code": response.status_code, "message": response.text,
                            "payload_sent": payload}
        except requests.exceptions.RequestException as e:
            logger.error(f"Network/Request error creating issue in {project_key}: {str(e)}")
            return {"error": True, "message": f"RequestException: {str(e)}"}
        except Exception as e:  # Catch any other unexpected errors
            logger.error(f"An unexpected error occurred while creating issue in {project_key}: {str(e)}")
            return {"error": True, "message": f"Unexpected error: {str(e)}"}

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
