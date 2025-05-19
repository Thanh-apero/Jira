import logging
import requests

logger = logging.getLogger(__name__)


class VersionHandler:
    """
    Handles version-related operations such as getting project versions
    and issues by version.
    """

    def __init__(self, core):
        """Initialize with a JiraCore instance"""
        self.core = core

    def get_project_versions(self, project_key):
        """Get all versions for a project"""
        if not self.core.is_configured():
            logger.error("Jira API not configured. Cannot get project versions.")
            return []

        cache_key = f"versions_{project_key}"

        # Return from cache if valid
        if self.core._is_cache_valid(cache_key) and cache_key in self.core._projects_cache:
            logger.info(f"Using cached versions for project {project_key}")
            return self.core._projects_cache[cache_key]

        try:
            logger.info(f"Fetching versions for project {project_key}")
            response = requests.get(
                f"{self.core.jira_url}/rest/api/2/project/{project_key}/versions",
                auth=self.core.auth
            )

            if response.status_code == 200:
                versions = response.json()
                logger.info(f"Found {len(versions)} versions for project {project_key}")

                # Sort versions by release date/sequence if available
                versions.sort(key=lambda v: v.get('releaseDate', ''), reverse=True)

                # Cache the result for 15 minutes
                self.core._set_cache('projects', cache_key, versions, expiry=15 * 60)
                return versions
            else:
                logger.error(f"Failed to fetch versions: {response.status_code} - {response.text}")
                return []
        except Exception as e:
            logger.error(f"Error getting versions for project {project_key}: {str(e)}")
            return []

    def get_issues_by_version(self, project_key, version_id):
        """Get issues for a specific version"""
        if not self.core.is_configured():
            logger.error("Jira API not configured. Cannot get version issues.")
            return []

        try:
            jql = f'project = {project_key} AND fixVersion = {version_id}'

            # Import here to avoid circular import
            from jira.issues import IssueHandler
            issue_handler = IssueHandler(self.core)
            issues = issue_handler.search_issues(
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
