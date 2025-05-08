#!/usr/bin/env python3
import os
import logging
import requests
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


def test_jira_connection():
    """Test connection to Jira API"""
    jira_url = os.getenv('JIRA_URL')
    jira_email = os.getenv('JIRA_USER_EMAIL')
    jira_token = os.getenv('JIRA_API_TOKEN')

    logger.info(f"Testing Jira API connection...")
    logger.info(f"Jira URL: {jira_url}")
    logger.info(f"Jira Email: {jira_email[:3]}...{jira_email[-10:] if len(jira_email) > 10 else jira_email}")
    logger.info(f"Jira Token: {'*' * 5 + jira_token[-5:] if jira_token else 'Not set'}")

    if not all([jira_url, jira_email, jira_token]):
        logger.error("Missing required Jira API credentials")
        return False

    try:
        logger.info(f"Making request to {jira_url}/rest/api/2/project")
        response = requests.get(
            f"{jira_url}/rest/api/2/project",
            auth=(jira_email, jira_token)
        )

        if response.status_code == 200:
            projects = response.json()
            logger.info(f"Connection successful! Found {len(projects)} projects")
            for idx, project in enumerate(projects[:5]):  # Show first 5 projects
                logger.info(f"Project {idx + 1}: {project.get('name')} ({project.get('key')})")
            if len(projects) > 5:
                logger.info(f"...and {len(projects) - 5} more projects")
            return True
        else:
            logger.error(f"API request failed with status code: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Exception during API request: {str(e)}")
        return False


if __name__ == "__main__":
    test_jira_connection()
