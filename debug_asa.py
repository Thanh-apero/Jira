#!/usr/bin/env python3
import os
import logging
from dotenv import load_dotenv
from jira import JiraAPI

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


def test_asa_project():
    """Test finding reopened bugs in the ASA project"""
    jira_api = JiraAPI()

    # Check if Jira API is configured
    if not jira_api.is_configured():
        logger.error("Jira API is not configured. Please check credentials.")
        return

    # Test connection first
    projects = jira_api.get_all_projects()
    if not projects:
        logger.error("Could not retrieve any projects from Jira.")
        return

    # Check if ASA project exists
    asa_exists = any(p.get('key') == 'ASA' for p in projects)
    if not asa_exists:
        logger.error("ASA project not found in available projects.")
        logger.info("Available projects: %s", ", ".join([p.get('key') for p in projects[:10]]))
        return

    logger.info("Testing ASA project reopened bugs...")

    try:
        # Try to get bugs in ASA project first
        from jira.issues import IssueHandler
        issue_handler = getattr(jira_api, '_issue_handler', None)
        if not issue_handler:
            issue_handler = IssueHandler(jira_api.core)

        jql = "project = ASA AND issuetype = Bug"
        logger.info("Executing JQL: %s", jql)

        # First get bugs without changelog to check if query works
        bugs = issue_handler.search_issues(
            jql,
            fields="key,summary,status",
            max_results=10,
            use_cache=False
        )

        logger.info("Found %d bugs in ASA project", len(bugs) if bugs else 0)

        if not bugs:
            logger.info("No bugs found in ASA project, nothing to reopen.")
            return

        # Now try with changelog
        logger.info("Trying to get bugs with changelog...")
        bugs_with_changelog = issue_handler.search_issues(
            jql,
            fields="key,summary,status",
            expand="changelog",
            max_results=10,
            use_cache=False
        )

        logger.info("Found %d bugs with changelog in ASA project",
                    len(bugs_with_changelog) if bugs_with_changelog else 0)

        # Try to debug the structure of the first bug
        if bugs_with_changelog and len(bugs_with_changelog) > 0:
            first_bug = bugs_with_changelog[0]
            logger.info("Structure of first bug: %s", first_bug.keys())

            # Check for changelog
            if 'changelog' not in first_bug:
                logger.error("Bug does not have changelog key!")
            else:
                changelog = first_bug.get('changelog')
                logger.info("Changelog structure: %s", changelog.keys() if changelog else None)

                # Check for histories
                if 'histories' not in changelog:
                    logger.error("Changelog does not have histories key!")
                else:
                    histories = changelog.get('histories', [])
                    logger.info("Number of history entries: %d", len(histories))

                    # Check the first history entry if available
                    if histories and len(histories) > 0:
                        logger.info("First history entry: %s", histories[0].keys())

        # Now try to find reopened bugs
        logger.info("Trying to find reopened bugs...")
        reopened_bugs = jira_api.find_reopened_bugs_by_jql('ASA')
        logger.info("Found %d reopened bugs in ASA project", len(reopened_bugs) if reopened_bugs else 0)

        return reopened_bugs
    except Exception as e:
        logger.exception("Error while testing ASA project: %s", str(e))


if __name__ == "__main__":
    test_asa_project()
