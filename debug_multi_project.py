#!/usr/bin/env python3
import os
import logging
import traceback
from dotenv import load_dotenv
from jira import JiraAPI
from project_management import ProjectManager

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


def test_multiple_projects():
    """Test finding reopened bugs across multiple projects including ASA"""
    jira_api = JiraAPI()
    project_manager = ProjectManager()

    # Check if Jira API is configured
    if not jira_api.is_configured():
        logger.error("Jira API is not configured. Please check credentials.")
        return

    # Get all projects
    all_projects = jira_api.get_all_projects()
    if not all_projects:
        logger.error("Could not retrieve any projects from Jira.")
        return

    # Test specific projects including ASA
    test_projects = ['ASA', 'QT', 'MASMB']  # Add projects to test

    # Check if test projects exist
    for project_key in test_projects:
        project_exists = any(p.get('key') == project_key for p in all_projects)
        if not project_exists:
            logger.warning("Project %s not found in available projects.", project_key)

    # Process each project separately
    for project_key in test_projects:
        logger.info("=" * 50)
        logger.info("Testing project: %s", project_key)

        try:
            # Try to find reopened bugs for this project
            logger.info("Finding reopened bugs for project %s...", project_key)
            project_reopened_bugs = jira_api.find_reopened_bugs_by_jql(
                project_key,
                start_date=None,
                end_date=None
            )

            logger.info("Found %d reopened bugs in project %s",
                        len(project_reopened_bugs) if project_reopened_bugs else 0,
                        project_key)

            # Check the structure of bugs to identify potential NoneType issues
            if project_reopened_bugs:
                # Check the first bug's structure
                first_bug = project_reopened_bugs[0]
                logger.info("Sample bug key: %s", first_bug.get('key', 'Unknown'))
                logger.info("Sample bug has reopen_by: %s", first_bug.get('reopen_by', 'Not found'))
                logger.info("Sample bug has reopen_time: %s", first_bug.get('reopen_time', 'Not found'))
                logger.info("Sample bug has was_reopened: %s", first_bug.get('was_reopened', 'Not found'))
            else:
                logger.warning("No reopened bugs found for project %s", project_key)

        except Exception as e:
            logger.error("Error processing project %s: %s", project_key, str(e))
            logger.error("Traceback: %s", traceback.format_exc())

    # Now test get_project_statistics which might be failing
    logger.info("=" * 50)
    logger.info("Testing project statistics...")

    for project_key in test_projects:
        try:
            logger.info("Getting statistics for project %s...", project_key)

            # For ASA project, let's do more detailed debugging
            if project_key == 'ASA':
                logger.info("Detailed debugging for ASA project statistics...")

                # Get reopened bugs first to check their structure
                logger.info("Re-checking reopened bugs structure...")
                reopened_bugs = jira_api.find_reopened_bugs_by_jql('ASA')

                if reopened_bugs and len(reopened_bugs) > 0:
                    sample_bug = reopened_bugs[0]
                    logger.info("Sample bug keys: %s", list(sample_bug.keys()))
                    logger.info("Sample bug fields keys: %s",
                                list(sample_bug.get('fields', {}).keys()))

                    # Check the assignee structure
                    fields = sample_bug.get('fields', {})
                    assignee = fields.get('assignee')
                    logger.info("Assignee type: %s", type(assignee).__name__ if assignee is not None else "None")
                    logger.info("Assignee keys: %s",
                                list(assignee.keys()) if assignee and hasattr(assignee, 'keys') else "N/A")

                    # Log full sample bug data for inspection
                    logger.info("Full sample bug data: %s", sample_bug)

                else:
                    logger.warning("No reopened bugs found for ASA project during debug check")

                # Try to fetch participants manually 
                logger.info("Checking participants...")
                from jira.projects import ProjectHandler
                project_handler = getattr(jira_api, '_project_handler', None)
                if not project_handler:
                    project_handler = ProjectHandler(jira_api.core)

                participants = project_handler.get_project_participants(project_key)
                logger.info("Found %d participants in project %s", len(participants) if participants else 0,
                            project_key)
                logger.info("Participants sample: %s", participants[:2] if participants else "None")

                # Check issues
                logger.info("Checking issues...")
                from jira.issues import IssueHandler
                issue_handler = getattr(jira_api, '_issue_handler', None)
                if not issue_handler:
                    issue_handler = IssueHandler(jira_api.core)

                jql = f"project = {project_key}"
                issues = issue_handler.search_issues(
                    jql,
                    fields="key,summary,status,assignee,reporter,issuetype,priority,created,updated",
                    max_results=10,
                    use_cache=False
                )
                logger.info("Found %d issues in sample", len(issues) if issues else 0)

                if issues and len(issues) > 0:
                    logger.info("Sample issue keys: %s", list(issues[0].keys()))
                    logger.info("Sample issue data: %s", issues[0])

            # Try getting statistics
            project_stats = jira_api.get_project_statistics(project_key)

            if project_stats:
                logger.info("Project %s stats: %d total issues, %d reopened bugs",
                            project_key,
                            project_stats.get('total_issues', 0),
                            project_stats.get('reopened_bugs_count', 0))
            else:
                logger.error("Failed to get statistics for project %s", project_key)

        except Exception as e:
            logger.error("Error getting statistics for project %s: %s", project_key, str(e))
            logger.error("Traceback: %s", traceback.format_exc())


if __name__ == "__main__":
    test_multiple_projects()
