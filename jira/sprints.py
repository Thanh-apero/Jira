import logging
import requests

logger = logging.getLogger(__name__)


class SprintHandler:
    """
    Handles sprint-related operations such as getting active sprints
    and adding issues to sprints.
    """

    def __init__(self, core):
        """Initialize with a JiraCore instance"""
        self.core = core

    def get_active_sprints(self, project_key, use_cache=True):
        """Get active sprints for a project"""
        cache_key = f"active_sprints_{project_key}"

        # Return from cache if valid (short cache time for active sprints)
        if use_cache and self.core._is_cache_valid(cache_key) and cache_key in self.core._sprints_cache:
            logger.info(f"Using cached active sprints for {project_key}")
            return self.core._sprints_cache[cache_key]

        if not self.core.is_configured():
            logger.error("Jira API credentials not configured")
            return []

        try:
            logger.info(f"Fetching active sprints for project {project_key}")

            # First get all boards for the project
            boards_response = requests.get(
                f"{self.core.jira_url}/rest/agile/1.0/board",
                params={"projectKeyOrId": project_key},
                auth=self.core.auth
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
                    f"{self.core.jira_url}/rest/agile/1.0/board/{board_id}/sprint",
                    params={"state": "active,future"},  # Get both active and future sprints
                    auth=self.core.auth
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
            self.core._set_cache('sprints', cache_key, active_sprints, 5 * 60)
            return active_sprints

        except Exception as e:
            logger.error(f"Error getting active sprints: {str(e)}")
            return []

    def add_issue_to_sprint(self, sprint_id, issue_key):
        """Add an issue to a sprint"""
        if not self.core.is_configured():
            logger.error("Jira API credentials not configured")
            return False

        try:
            logger.info(f"Adding issue {issue_key} to sprint {sprint_id}")

            response = requests.post(
                f"{self.core.jira_url}/rest/agile/1.0/sprint/{sprint_id}/issue",
                json={"issues": [issue_key]},
                auth=self.core.auth
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
