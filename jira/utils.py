import logging
import json
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


def format_date(date_obj, format="%Y-%m-%d"):
    """Format a date object to a string in the specified format"""
    if date_obj is None:
        return None

    if isinstance(date_obj, str):
        try:
            date_obj = datetime.fromisoformat(date_obj.replace('Z', '+00:00'))
        except ValueError:
            return date_obj

    try:
        return date_obj.strftime(format)
    except Exception as e:
        logger.error(f"Error formatting date {date_obj}: {str(e)}")
        return str(date_obj)


def parse_jira_date(date_str):
    """Parse a date string from Jira API to a datetime object"""
    if not date_str:
        return None

    try:
        # Handle ISO format with timezone
        if 'T' in date_str:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        # Handle simple date format
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError as e:
        logger.error(f"Error parsing date {date_str}: {str(e)}")
        return None


def days_between(date1, date2=None):
    """Calculate days between two dates, or between a date and now"""
    if date1 is None:
        return None

    if isinstance(date1, str):
        date1 = parse_jira_date(date1)

    if date2 is None:
        date2 = datetime.now(date1.tzinfo if hasattr(date1, 'tzinfo') else None)
    elif isinstance(date2, str):
        date2 = parse_jira_date(date2)

    try:
        delta = date2 - date1
        return delta.days
    except Exception as e:
        logger.error(f"Error calculating days between {date1} and {date2}: {str(e)}")
        return None


def create_jql_filter(project_keys=None, issue_types=None, statuses=None, since=None, until=None,
                      assignee=None, reporter=None):
    """
    Create a JQL filter string from the provided parameters
    
    Args:
        project_keys (list): List of project keys to include
        issue_types (list): List of issue types to filter
        statuses (list): List of statuses to filter
        since (str): Start date for the filter (YYYY-MM-DD)
        until (str): End date for the filter (YYYY-MM-DD)
        assignee (str): Assignee username or display name
        reporter (str): Reporter username or display name
        
    Returns:
        str: A JQL query string
    """
    jql_parts = []

    if project_keys:
        if len(project_keys) == 1:
            jql_parts.append(f"project = {project_keys[0]}")
        else:
            project_clause = " OR ".join([f"project = {key}" for key in project_keys])
            jql_parts.append(f"({project_clause})")

    if issue_types:
        if len(issue_types) == 1:
            jql_parts.append(f'issuetype = "{issue_types[0]}"')
        else:
            types_clause = " OR ".join([f'issuetype = "{t}"' for t in issue_types])
            jql_parts.append(f"({types_clause})")

    if statuses:
        if len(statuses) == 1:
            jql_parts.append(f'status = "{statuses[0]}"')
        else:
            status_clause = " OR ".join([f'status = "{s}"' for s in statuses])
            jql_parts.append(f"({status_clause})")

    if since:
        jql_parts.append(f'updated >= "{since}"')

    if until:
        jql_parts.append(f'updated <= "{until}"')

    if assignee:
        jql_parts.append(f'assignee = "{assignee}"')

    if reporter:
        jql_parts.append(f'reporter = "{reporter}"')

    return " AND ".join(jql_parts)
