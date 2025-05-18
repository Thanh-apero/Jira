#!/usr/bin/env python3
import os
import logging
import sys
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Import project modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jira_api import JiraAPI

# Load environment variables
load_dotenv()


def test_jira_statuses():
    """Test getting all available statuses in Jira"""
    jira = JiraAPI()

    logger.info("Testing: Getting all Jira statuses")

    if not jira.is_configured():
        logger.error("Jira API is not configured")
        return False

    all_statuses = jira.get_available_statuses()
    if not all_statuses:
        logger.error("Failed to get Jira statuses")
        return False

    logger.info(f"Found {len(all_statuses)} statuses in Jira")
    for status in all_statuses:
        logger.info(f"Status: {status['name']} (Category: {status.get('category', 'N/A')})")

    return True


def test_status_transitions(project_key):
    """Test analyzing status transitions in a project"""
    jira = JiraAPI()

    logger.info(f"Testing: Analyzing status transitions in project {project_key}")

    if not jira.is_configured():
        logger.error("Jira API is not configured")
        return False

    # Test with 20 recent bugs to get a good sample
    transitions = jira.test_get_status_transitions(project_key, 20)
    if not transitions:
        logger.error(f"Failed to analyze transitions or no bugs found in project {project_key}")
        return False

    # Show all statuses
    logger.info("All available statuses in Jira:")
    for status in transitions.get("all_statuses", []):
        logger.info(f"- {status}")

    # Show the most common transitions
    logger.info("Most common status transitions:")
    for transition, count in transitions.get("transitions_found", [])[:10]:  # Top 10
        logger.info(f"- {transition}: {count} occurrences")

    # Show potential reopen transitions
    logger.info("Potential reopen transitions:")
    for transition, count in transitions.get("possible_reopen_transitions", []):
        logger.info(f"- {transition}: {count} occurrences")

    return True


def test_reopened_bugs(project_key):
    """Test finding reopened bugs in a project"""
    jira = JiraAPI()

    logger.info(f"Testing: Finding reopened bugs in project {project_key}")

    if not jira.is_configured():
        logger.error("Jira API is not configured")
        return False

    # Find reopened bugs in the last 30 days
    today = datetime.now()
    thirty_days_ago = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    today_str = today.strftime("%Y-%m-%d")

    reopened_bugs = jira.find_reopened_bugs_by_jql(
        project_key,
        start_date=thirty_days_ago,
        end_date=today_str
    )

    if reopened_bugs is None:
        logger.error(f"Error finding reopened bugs in project {project_key}")
        return False

    logger.info(f"Found {len(reopened_bugs)} reopened bugs in project {project_key} (last 30 days)")

    # Show details of each reopened bug
    for i, bug in enumerate(reopened_bugs[:10], 1):  # Show at most 10
        issue_key = bug.get('key')
        summary = bug.get('fields', {}).get('summary', 'No summary')
        assignee = bug.get('fields', {}).get('assignee', {}).get('displayName', 'Unassigned')
        from_status = bug.get('reopen_from', 'Unknown')
        to_status = bug.get('reopen_to', 'Unknown')
        reopen_time = bug.get('reopen_time', 'Unknown')
        reopened_by = bug.get('reopen_by', 'Unknown')

        logger.info(f"Bug {i}: {issue_key} - {summary}")
        logger.info(f"  Assignee: {assignee}")
        logger.info(f"  Reopened: {from_status} → {to_status} on {reopen_time}")
        logger.info(f"  Reopened by: {reopened_by}")

    if len(reopened_bugs) > 10:
        logger.info(f"...and {len(reopened_bugs) - 10} more reopened bugs")

    return True


if __name__ == "__main__":
    # Check if project key is provided
    if len(sys.argv) < 2:
        logger.error("Please provide a project key as argument")
        logger.error("Usage: python test_reopened_bugs.py PROJECT_KEY")
        sys.exit(1)

    project_key = sys.argv[1]

    # Run tests in sequence
    status_test = test_jira_statuses()
    transitions_test = test_status_transitions(project_key)
    reopened_test = test_reopened_bugs(project_key)

    # Report overall results
    logger.info("\n--- TEST RESULTS ---")
    logger.info(f"Jira statuses test: {'PASSED' if status_test else 'FAILED'}")
    logger.info(f"Status transitions test: {'PASSED' if transitions_test else 'FAILED'}")
    logger.info(f"Reopened bugs test: {'PASSED' if reopened_test else 'FAILED'}")
