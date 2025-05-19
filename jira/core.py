import os
import logging
import requests
import time
import json
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Path to store notification history
NOTIFICATION_HISTORY_FILE = "notification_history.json"


class JiraCore:
    """
    Core functionality for interacting with Jira API.
    Handles authentication, basic requests, caching, and configuration.
    """

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

    # Cache management methods
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

    # Notification history methods
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
