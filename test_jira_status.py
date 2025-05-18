#!/usr/bin/env python3
import logging
from jira_api import JiraAPI

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def test_jira_statuses():
    """Log all available statuses in Jira"""
    jira = JiraAPI()

    if not jira.is_configured():
        logger.error("Jira API not configured")
        return

    statuses = jira.get_available_statuses()
    logger.info(f"Found {len(statuses)} statuses in Jira:")

    # Create a neat table-like output
    logger.info("-" * 80)
    logger.info(f"{'Status Name':<30} | {'Category':<20} | {'ID':<10}")
    logger.info("-" * 80)

    for status in statuses:
        logger.info(f"{status['name']:<30} | {status.get('category', 'N/A'):<20} | {status['id']:<10}")

    logger.info("-" * 80)

    # Also check for actual transitions from the history of some bugs
    project_key = "AIP339"  # Replace with your project key
    transitions = jira.test_get_status_transitions(project_key, limit=20)

    if transitions:
        logger.info("\nActual status transitions found (top 10):")
        logger.info("-" * 80)
        for transition, count in transitions.get("transitions_found", [])[:10]:
            logger.info(f"{transition} ({count} occurrences)")
        logger.info("-" * 80)


if __name__ == "__main__":
    test_jira_statuses()
