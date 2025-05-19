#!/usr/bin/env python3
import os
import logging
import traceback
import pprint
from dotenv import load_dotenv
from jira import JiraAPI
from jira.statistics import StatisticsHandler
from project_management import ProjectManager

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


def debug_asa_statistics():
    """Debug the ASA project statistics with detailed tracing"""
    jira_api = JiraAPI()

    # Check if Jira API is configured
    if not jira_api.is_configured():
        logger.error("Jira API is not configured. Please check credentials.")
        return

    logger.info("=" * 50)
    logger.info("DETAILED ASA PROJECT STATISTICS DEBUG")
    logger.info("=" * 50)

    # Get reopened bugs first
    logger.info("1. Checking reopened bugs for ASA project")
    reopened_bugs = jira_api.find_reopened_bugs_by_jql('ASA')

    if reopened_bugs:
        logger.info("   ✓ Found %d reopened bugs", len(reopened_bugs))

        # Inspect the first bug to verify its structure
        first_bug = reopened_bugs[0]
        logger.info("   ✓ First bug has key: %s", first_bug.get('key', '?'))
        logger.info("   ✓ First bug has fields: %s", 'Yes' if 'fields' in first_bug else 'No')
    else:
        logger.error("   ✗ No reopened bugs found")

    # Manually recreate the steps in get_project_statistics
    logger.info("2. Manually recreating get_project_statistics steps")

    # 2.1 Get all issues
    logger.info("2.1. Getting all issues in project ASA")
    from jira.issues import IssueHandler
    issue_handler = IssueHandler(jira_api.core)

    all_issues = issue_handler.search_issues(
        "project = ASA",
        fields="key,summary,status,assignee,reporter,issuetype,priority,created,updated,comment",
        max_results=100,
        use_cache=False
    )

    if all_issues:
        logger.info("   ✓ Found %d issues", len(all_issues))
        # Check the first issue structure
        first_issue = all_issues[0]
        logger.info("   ✓ First issue has key: %s", first_issue.get('key', '?'))
        logger.info("   ✓ First issue has fields: %s", 'Yes' if 'fields' in first_issue else 'No')
    else:
        logger.error("   ✗ No issues found")
        return

    # 2.2 Process issues to count types
    logger.info("2.2. Processing issues to count types")
    status_counts = {}
    issue_types = {}
    completed_tasks_count = 0
    bugs_count = 0

    try:
        for issue in all_issues:
            fields = issue.get('fields', {})
            if not fields:
                logger.warning("Issue %s has no fields", issue.get('key', '?'))
                continue

            # Get status and count
            status = fields.get('status', {}).get('name', 'Unknown')
            if status in status_counts:
                status_counts[status] += 1
            else:
                status_counts[status] = 1

            # Check if completed
            if status.lower() in ['done', 'closed', 'resolved', 'completed']:
                completed_tasks_count += 1

            # Get issue type and count
            issue_type = fields.get('issuetype', {}).get('name', 'Unknown')
            if issue_type in issue_types:
                issue_types[issue_type] += 1
            else:
                issue_types[issue_type] = 1

            # Count bugs
            if issue_type.lower() == 'bug':
                bugs_count += 1

        logger.info("   ✓ Processed issues: %d status types, %d issue types, %d bugs, %d completed",
                    len(status_counts), len(issue_types), bugs_count, completed_tasks_count)
    except Exception as e:
        logger.error("   ✗ Error processing issues: %s", str(e))
        logger.error(traceback.format_exc())
        return

    # 2.3 Get participants
    logger.info("2.3. Getting participants for ASA project")
    from jira.projects import ProjectHandler
    project_handler = ProjectHandler(jira_api.core)

    try:
        participants = project_handler.get_project_participants('ASA')
        logger.info("   ✓ Found %d participants", len(participants) if participants else 0)
        if participants and len(participants) > 0:
            logger.info("   ✓ First participant: %s", participants[0])
        else:
            logger.info("   ℹ No participants found, will use empty list")
            participants = []
    except Exception as e:
        logger.error("   ✗ Error getting participants: %s", str(e))
        logger.error(traceback.format_exc())
        participants = []

    # 2.4 Process reopened_bugs for reopener stats
    logger.info("2.4. Processing reopened bugs for reopener stats")
    reopener_stats = {}

    try:
        for bug in reopened_bugs:
            if not bug:
                logger.warning("   ℹ Found None bug in reopened_bugs list, skipping")
                continue

            reopener = bug.get('reopen_by', 'Unknown')
            if reopener in reopener_stats:
                reopener_stats[reopener] += 1
            else:
                reopener_stats[reopener] = 1

        logger.info("   ✓ Found %d unique reopeners", len(reopener_stats))

        # Sort reopeners
        sorted_reopeners = sorted(
            [(name, count) for name, count in reopener_stats.items()],
            key=lambda x: x[1],
            reverse=True
        )
        logger.info("   ✓ Top reopeners: %s", sorted_reopeners[:3] if sorted_reopeners else "None")
    except Exception as e:
        logger.error("   ✗ Error processing reopener stats: %s", str(e))
        logger.error(traceback.format_exc())
        sorted_reopeners = []

    # 2.5 Process bugs for assignee bug stats
    logger.info("2.5. Processing bugs for assignee stats")
    assignee_bug_stats = {}

    try:
        # First count all bugs by assignee
        for issue in all_issues:
            if not issue:
                logger.warning("   ℹ Found None issue in all_issues list, skipping")
                continue

            fields = issue.get('fields', {})
            if not fields:
                logger.warning("   ℹ Issue %s has no fields, skipping", issue.get('key', '?'))
                continue

            issue_type = fields.get('issuetype', {}).get('name', 'Unknown')
            if issue_type.lower() == 'bug':
                assignee_obj = fields.get('assignee')
                assignee = assignee_obj.get('displayName', 'Unassigned') if assignee_obj else 'Unassigned'

                if assignee in assignee_bug_stats:
                    assignee_bug_stats[assignee]['total'] += 1
                else:
                    assignee_bug_stats[assignee] = {'total': 1, 'reopened': 0}

        logger.info("   ✓ Found %d assignees with bugs", len(assignee_bug_stats))

        # Now add reopened bugs count
        logger.info("2.6. Processing reopened bugs for assignee stats")
        for bug in reopened_bugs:
            if not bug:
                logger.warning("   ℹ Found None bug in reopened_bugs list, skipping")
                continue

            fields = bug.get('fields', {})
            if not fields:
                logger.warning("   ℹ Bug %s has no fields, skipping", bug.get('key', '?'))
                logger.warning("   ℹ Bug structure: %s", list(bug.keys()))
                continue

            # Print debug info for the first bug
            if bug == reopened_bugs[0]:
                logger.info("   ℹ First reopened bug fields structure: %s", list(fields.keys()))
                logger.info("   ℹ First reopened bug assignee field: %s",
                            "Present" if 'assignee' in fields else "Missing")
                if 'assignee' in fields:
                    assignee_obj = fields.get('assignee')
                    logger.info("   ℹ First reopened bug assignee object type: %s", type(assignee_obj).__name__)
                    if assignee_obj:
                        logger.info("   ℹ First reopened bug assignee object keys: %s",
                                    list(assignee_obj.keys()) if hasattr(assignee_obj, 'keys') else "No keys method")

            assignee_obj = fields.get('assignee')
            assignee_name = assignee_obj.get('displayName', 'Unassigned') if assignee_obj else 'Unassigned'

            if assignee_name in assignee_bug_stats:
                assignee_bug_stats[assignee_name]['reopened'] += 1
            else:
                # This shouldn't happen if all bugs are counted correctly above
                logger.warning("   ℹ Assignee %s not found in the bugs list but has reopened bugs", assignee_name)
                assignee_bug_stats[assignee_name] = {'total': 1, 'reopened': 1}

        # Sort assignees
        sorted_assignees = sorted(
            [(name, stats) for name, stats in assignee_bug_stats.items()],
            key=lambda x: x[1]['total'],
            reverse=True
        )

        logger.info("   ✓ Top assignees with bugs: %s", sorted_assignees[:3] if sorted_assignees else "None")
    except Exception as e:
        logger.error("   ✗ Error processing assignee bug stats: %s", str(e))
        logger.error(traceback.format_exc())
        sorted_assignees = []

    # 2.7 Build statistics response
    logger.info("2.7. Building statistics response")
    try:
        statistics = {
            'total_issues': len(all_issues),
            'completed_tasks_count': completed_tasks_count,
            'bugs_count': bugs_count,
            'reopened_bugs_count': len(reopened_bugs),
            'status_counts': status_counts,
            'issue_types': issue_types,
            'recent_issues': [],  # Skip for simplicity
            'participants': participants,
            'total_participants': len(participants),
            'reopeners': sorted_reopeners,
            'assignee_bug_stats': sorted_assignees
        }

        logger.info("   ✓ Successfully built statistics dictionary")
        logger.info("   ✓ Statistics overview: %d issues, %d bugs, %d reopened",
                    statistics['total_issues'], statistics['bugs_count'], statistics['reopened_bugs_count'])

        return statistics
    except Exception as e:
        logger.error("   ✗ Error building statistics: %s", str(e))
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    statistics = debug_asa_statistics()
    if statistics:
        logger.info("=" * 50)
        logger.info("STATISTICS SUCCESSFULLY GENERATED")
        logger.info("=" * 50)
