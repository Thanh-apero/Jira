#!/usr/bin/env python3
"""
Test script to verify the functionality of the refactored jira package
"""
import sys
import logging
import os
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


def test_imports():
    """Test that all components import correctly"""
    try:
        from jira import JiraAPI
        from jira.core import JiraCore
        from jira.issues import IssueHandler
        from jira.projects import ProjectHandler
        from jira.sprints import SprintHandler
        from jira.versions import VersionHandler
        from jira.statistics import StatisticsHandler
        from jira.utils import format_date, parse_jira_date, create_jql_filter

        logger.info("✓ All imports successful")
        return True
    except Exception as e:
        logger.error(f"✗ Import error: {str(e)}")
        return False


def test_core_initialization():
    """Test that JiraAPI initializes correctly"""
    try:
        from jira import JiraAPI

        # Try to initialize from environment variables
        jira_api = JiraAPI()

        if jira_api.is_configured():
            logger.info("✓ JiraAPI initialized successfully from environment variables")
        else:
            logger.warning("JiraAPI initialized but credentials not found in environment")

        # Test direct initialization
        jira_api2 = JiraAPI(
            jira_url=os.getenv('JIRA_URL', 'https://example.atlassian.net'),
            jira_email=os.getenv('JIRA_USER_EMAIL', 'test@example.com'),
            jira_token=os.getenv('JIRA_API_TOKEN', 'dummy_token')
        )

        logger.info("✓ JiraAPI initialized successfully with explicit parameters")
        return True
    except Exception as e:
        logger.error(f"✗ Initialization error: {str(e)}")
        return False


def test_project_handler():
    """Test that ProjectHandler works correctly"""
    try:
        from jira import JiraAPI

        jira_api = JiraAPI()

        if not jira_api.is_configured():
            logger.warning("Skipping project test: JiraAPI not configured")
            return True

        # Try to get projects (this should work even without credentials)
        projects = jira_api.projects.get_all_projects(use_cache=False)
        logger.info(f"✓ ProjectHandler returned {len(projects)} projects")
        return True
    except Exception as e:
        logger.error(f"✗ ProjectHandler error: {str(e)}")
        return False


def test_utils():
    """Test utility functions"""
    try:
        from jira.utils import format_date, parse_jira_date, days_between, create_jql_filter
        from datetime import datetime, timedelta

        # Test date formatting
        date = datetime.now()
        formatted = format_date(date)
        logger.info(f"✓ Formatted date: {formatted}")

        # Test JQL creation
        jql = create_jql_filter(
            project_keys=["TEST", "DEMO"],
            issue_types=["Bug"],
            statuses=["Open", "In Progress"],
            since="2023-01-01",
            assignee="currentUser()"
        )
        logger.info(f"✓ Created JQL: {jql}")

        return True
    except Exception as e:
        logger.error(f"✗ Utils error: {str(e)}")
        return False


def run_all_tests():
    """Run all tests and return overall status"""
    logger.info("Starting jira package tests")

    test_functions = [
        test_imports,
        test_core_initialization,
        test_project_handler,
        test_utils
    ]

    results = [test() for test in test_functions]
    success = all(results)

    if success:
        logger.info("✓ All tests passed")
    else:
        logger.error(f"✗ {results.count(False)} tests failed")

    return success


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
