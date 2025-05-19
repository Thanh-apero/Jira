import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class StatisticsHandler:
    """
    Handles operations related to generating statistics about projects,
    reopened bugs, and issue status transitions.
    """

    def __init__(self, core):
        """Initialize with a JiraCore instance"""
        self.core = core

    def get_project_statistics(self, project_key, start_date=None, end_date=None, participant=None):
        """
        Get project statistics including total issues, status breakdown, etc.
        """
        if not self.core.is_configured():
            logger.error("Jira API credentials not configured")
            return {}

        try:
            # Base JQL to get all issues in the project
            jql_parts = [f"project = {project_key}"]

            # Add time constraints if provided
            if start_date:
                jql_parts.append(f'updated >= "{start_date}"')
            if end_date:
                jql_parts.append(f'updated <= "{end_date}"')

            # Add participant filter if provided
            if participant:
                # Only filter by assignee as requested
                jql_parts.append(f'assignee = "{participant}"')

            jql = " AND ".join(jql_parts)

            # OPTIMIZATION: Get all issues in a single query with all needed fields
            # This reduces the number of API calls significantly
            from jira.issues import IssueHandler
            issue_handler = IssueHandler(self.core)

            try:
                all_issues = issue_handler.search_issues(
                    jql,
                    fields="key,summary,status,assignee,reporter,issuetype,priority,created,updated,comment",
                    max_results=500,  # Reasonable limit for statistics
                    use_cache=False,  # Always fetch fresh data
                    expiry=300  # Cache for 5 minutes (not used due to use_cache=False)
                )
            except Exception as e:
                logger.error(f"Error fetching issues for project {project_key} with JQL '{jql}': {str(e)}")
                all_issues = []

            if not all_issues:
                logger.info(f"No issues found in project {project_key}")
                return {
                    'total_issues': 0,
                    'completed_tasks_count': 0,
                    'bugs_count': 0,
                    'reopened_bugs_count': 0,
                    'status_counts': {},
                    'issue_types': {},
                    'recent_issues': [],
                    'participants': [],
                    'total_participants': 0,
                    'reopeners': [],
                    'assignee_bug_stats': []
                }

            # Count issues by status and type
            status_counts = {}
            issue_types = {}
            completed_tasks_count = 0
            bugs_count = 0
            recent_issues = []

            # Process all issues in a single pass (no additional API calls)
            for issue in all_issues:
                if not issue:
                    continue

                fields = issue.get('fields', {})
                if not fields:
                    continue

                try:
                    # Get status and count
                    status_obj = fields.get('status')
                    if status_obj is None:
                        continue

                    status = status_obj.get('name', 'Unknown')
                    if status in status_counts:
                        status_counts[status] += 1
                    else:
                        status_counts[status] = 1

                    # Check if completed
                    if status.lower() in ['done', 'closed', 'resolved', 'completed']:
                        completed_tasks_count += 1

                    # Get issue type and count
                    issue_type_obj = fields.get('issuetype')
                    if not issue_type_obj:
                        continue

                    issue_type = issue_type_obj.get('name', 'Unknown')
                    if issue_type in issue_types:
                        issue_types[issue_type] += 1
                    else:
                        issue_types[issue_type] = 1

                    # Count bugs
                    if issue_type.lower() == 'bug':
                        bugs_count += 1

                    # Add to recent issues list
                    try:
                        recent_issue = {
                            'key': issue.get('key', 'Unknown'),
                            'summary': fields.get('summary', 'No summary'),
                            'status': status,
                            'type': issue_type
                        }

                        # Safely add assignee
                        assignee_obj = fields.get('assignee')
                        if assignee_obj and isinstance(assignee_obj, dict):
                            recent_issue['assignee'] = assignee_obj.get('displayName')
                        else:
                            recent_issue['assignee'] = None

                        recent_issue['updated'] = fields.get('updated')
                        recent_issues.append(recent_issue)
                    except Exception as e:
                        logger.error(f"Error processing recent issue: {str(e)}")
                        continue
                except Exception as e:
                    logger.error(f"Error processing issue {issue.get('key', 'Unknown')}: {str(e)}")
                    continue

            # Sort and limit recent issues
            try:
                if recent_issues:
                    recent_issues.sort(key=lambda x: x.get('updated', ''), reverse=True)
                    recent_issues = recent_issues[:50]  # Limit to most recent 50
            except Exception as e:
                logger.error(f"Error sorting recent issues: {str(e)}")
                recent_issues = []

            # OPTIMIZATION: Get participants with caching
            # We don't need to recalculate this for every statistics request
            from jira.projects import ProjectHandler
            project_handler = ProjectHandler(self.core)

            try:
                participants = project_handler.get_project_participants(project_key)
                if participants is None:
                    participants = []
            except Exception as e:
                logger.error(f"Error getting participants for project {project_key}: {str(e)}")
                participants = []

            # Get reopened bugs (filtered to bugs only to reduce API calls)
            try:
                reopened_bugs = self.find_reopened_bugs_by_jql(
                    project_key,
                    start_date=start_date,
                    end_date=end_date,
                    participant=participant
                )

                if reopened_bugs is None:
                    reopened_bugs = []
            except Exception as e:
                logger.error(f"Error finding reopened bugs for project {project_key}: {str(e)}")
                reopened_bugs = []

            reopened_bugs_count = len(reopened_bugs) if reopened_bugs else 0

            # NEW: Gather statistics about who reopened bugs
            reopener_stats = {}

            try:
                for bug in reopened_bugs:
                    if not bug:
                        continue  # Skip None values

                    reopener = bug.get('reopen_by', 'Unknown')
                    if reopener in reopener_stats:
                        reopener_stats[reopener] += 1
                    else:
                        reopener_stats[reopener] = 1
            except Exception as e:
                logger.error(f"Error gathering reopener stats: {str(e)}")

            # Sort reopeners by number of reopens (most first)
            try:
                sorted_reopeners = sorted(
                    [(name, count) for name, count in reopener_stats.items()],
                    key=lambda x: x[1],
                    reverse=True
                )
            except Exception as e:
                logger.error(f"Error sorting reopeners: {str(e)}")
                sorted_reopeners = []

            # NEW: Gather statistics about bugs by assignee
            assignee_bug_stats = {}

            try:
                for issue in all_issues:
                    if not issue:
                        continue

                    fields = issue.get('fields', {})
                    if not fields:
                        continue

                    issue_type_obj = fields.get('issuetype')
                    if not issue_type_obj:
                        continue

                    issue_type = issue_type_obj.get('name', 'Unknown')

                    if issue_type and issue_type.lower() == 'bug':
                        assignee_obj = fields.get('assignee')
                        assignee = assignee_obj.get('displayName', 'Unassigned') if assignee_obj else 'Unassigned'

                        if assignee in assignee_bug_stats:
                            assignee_bug_stats[assignee]['total'] += 1
                        else:
                            assignee_bug_stats[assignee] = {'total': 1, 'reopened': 0}
            except Exception as e:
                logger.error(f"Error processing bug assignee stats: {str(e)}")

            # Add reopened bugs to assignee stats
            try:
                for bug in reopened_bugs:
                    if not bug:
                        continue  # Skip None values

                    fields = bug.get('fields', {})
                    if not fields:
                        logger.warning(f"Bug {bug.get('key', 'unknown')} has no fields, skipping for assignee stats")
                        continue  # Skip bugs with no fields

                    try:
                        assignee = fields.get('assignee', {})
                        # Extra check for assignee object
                        if not assignee:
                            assignee_name = 'Unassigned'
                        else:
                            assignee_name = assignee.get('displayName', 'Unassigned') if assignee else 'Unassigned'

                        if assignee_name in assignee_bug_stats:
                            assignee_bug_stats[assignee_name]['reopened'] += 1
                        else:
                            assignee_bug_stats[assignee_name] = {'total': 1, 'reopened': 1}
                    except Exception as e:
                        logger.error(f"Error processing bug for assignee stats: {str(e)}")
                        logger.error(
                            f"Bug data: {bug.get('key')}, fields available: {list(fields.keys()) if fields else 'None'}")
            except Exception as e:
                logger.error(f"Error processing reopened bugs for assignee stats: {str(e)}")

            # Sort assignees by total bugs (most first)
            try:
                sorted_assignees = sorted(
                    [(name, stats) for name, stats in assignee_bug_stats.items()],
                    key=lambda x: x[1]['total'],
                    reverse=True
                )
            except Exception as e:
                logger.error(f"Error sorting assignee stats: {str(e)}")
                sorted_assignees = []

            # Build statistics response
            try:
                statistics = {
                    'total_issues': len(all_issues),
                    'completed_tasks_count': completed_tasks_count,
                    'bugs_count': bugs_count,
                    'reopened_bugs_count': reopened_bugs_count,
                    'status_counts': status_counts,
                    'issue_types': issue_types,
                    'recent_issues': recent_issues,
                    'participants': participants,
                    'total_participants': len(participants) if participants else 0,
                    # New statistics
                    'reopeners': sorted_reopeners,
                    'assignee_bug_stats': sorted_assignees
                }

                logger.info(
                    f"Generated statistics for project {project_key}: {bugs_count} bugs, {reopened_bugs_count} reopened bugs")
                return statistics
            except Exception as e:
                logger.error(f"Error creating or caching statistics for project {project_key}: {str(e)}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")

                # Return a minimal valid statistics object
                return {
                    'total_issues': len(all_issues) if all_issues else 0,
                    'completed_tasks_count': completed_tasks_count,
                    'bugs_count': bugs_count,
                    'reopened_bugs_count': reopened_bugs_count,
                    'status_counts': status_counts or {},
                    'issue_types': issue_types or {},
                    'recent_issues': [],
                    'participants': [],
                    'total_participants': 0,
                    'reopeners': sorted_reopeners or [],
                    'assignee_bug_stats': sorted_assignees or []
                }

        except Exception as e:
            logger.error(f"Error generating project statistics: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {}

    def test_get_status_transitions(self, project_key, limit=10):
        """
        Test function to get actual status transitions from a project's bugs
        This helps identify the real status names and flow in your Jira instance
        """
        if not self.core.is_configured():
            logger.error("Jira API credentials not configured")
            return {}

        try:
            # Get bugs in the project
            from jira.issues import IssueHandler
            issue_handler = IssueHandler(self.core)
            jql = f"project = {project_key} AND issuetype = Bug ORDER BY updated DESC"
            bugs = issue_handler.search_issues(
                jql,
                fields="key,summary,status",
                max_results=limit,
                use_cache=False
            )

            if not bugs:
                logger.info(f"No bugs found in project {project_key}")
                return {}

            # Get all available statuses
            all_statuses = self.core.get_available_statuses()
            status_names = {status["id"]: status["name"] for status in all_statuses}

            # Store transitions we find
            transitions = {}
            transitions_count = 0

            # For each bug, analyze status changes
            for bug in bugs:
                issue_key = bug.get('key')
                current_status = bug.get('fields', {}).get('status', {}).get('name', 'Unknown')

                # Get issue with changelog
                issue_detail = issue_handler.get_issue_with_changelog(issue_key)
                if not issue_detail:
                    continue

                changelog = issue_detail.get('changelog', {}).get('histories', [])

                logger.info(f"Analyzing status transitions for bug {issue_key} (current: {current_status})")

                # Process status changes
                for history in changelog:
                    for item in history.get('items', []):
                        if item.get('field') == 'status':
                            from_status = item.get('fromString', '(unknown)')
                            to_status = item.get('toString', '(unknown)')

                            # Log this transition
                            transition_key = f"{from_status} → {to_status}"
                            if transition_key not in transitions:
                                transitions[transition_key] = 0
                            transitions[transition_key] += 1
                            transitions_count += 1

                            logger.info(f"  {issue_key}: {from_status} → {to_status}")

            logger.info(f"Found {transitions_count} status transitions across {len(bugs)} bugs")
            # Sort transitions by frequency
            sorted_transitions = sorted(
                [(k, v) for k, v in transitions.items()],
                key=lambda x: x[1],
                reverse=True
            )

            # Determine what transitions might indicate a reopening
            reopen_candidates = []
            for transition, count in sorted_transitions:
                from_status, to_status = transition.split(' → ')
                # Look for patterns that might indicate reopening
                if any(review in from_status.lower() for review in
                       ["review", "resolved", "done", "closed", "completed"]) and any(
                        early in to_status.lower() for early in
                        ["open", "progress", "todo", "to do", "new", "backlog"]):
                    reopen_candidates.append((transition, count))

            result = {
                "all_statuses": [status["name"] for status in all_statuses],
                "transitions_found": sorted_transitions,
                "possible_reopen_transitions": reopen_candidates
            }

            return result

        except Exception as e:
            logger.error(f"Error testing status transitions: {str(e)}")
            return {}

    def find_reopened_bugs_by_jql(self, project_key, start_date=None, end_date=None, participant=None):
        """
        Find reopened bugs in a project using JQL.
        This function identifies bugs that have been reopened by looking at their status history.
        """
        if not self.core.is_configured():
            logger.error("Jira API credentials not configured")
            return []

        try:
            # First, get all bugs in the project
            jql_parts = [
                f"project = {project_key}",
                "issuetype = Bug"
            ]

            # Add time constraints if provided
            if start_date:
                jql_parts.append(f'updated >= "{start_date}"')
            if end_date:
                jql_parts.append(f'updated <= "{end_date}"')

            # Add participant filter if provided (assignee only as requested)
            if participant:
                jql_parts.append(f'assignee = "{participant}"')

            jql = " AND ".join(jql_parts)

            logger.info(f"Getting bugs with JQL: {jql}")

            # OPTIMIZATION: Get bugs with changelog in a single request
            # This reduces API calls by using the expand parameter
            from jira.issues import IssueHandler
            issue_handler = IssueHandler(self.core)
            all_bugs = issue_handler.search_issues(
                jql,
                fields="key,summary,status,assignee,reporter,issuetype,priority,created,updated",
                expand="changelog",  # Include changelog directly to avoid separate API calls
                max_results=200,
                use_cache=False
            )

            if not all_bugs:
                logger.info(f"No bugs found in project {project_key}")
                # Removed cache setting for empty result
                return []

            logger.info(f"Found {len(all_bugs)} bugs in project {project_key}, checking for reopens...")

            # For each bug, check its changelog to see if it was reopened
            reopened_bugs = []

            # Define status transition patterns that indicate reopening
            from_states = ["reviewing", "review", "in review", "under review", "done", "closed"]
            to_states = ["todo", "to do", "in progress", "reopened", "request", "backlog", "open"]

            for bug in all_bugs:
                if not bug:
                    continue  # Skip None values

                issue_key = bug.get('key')
                changelog = bug.get('changelog', {}).get('histories', [])  # Get changelog directly from expanded data

                # Look for status changes that indicate a reopen
                was_reopened = False
                reopen_time = None
                from_status_value = ""
                to_status_value = ""
                reopen_by = ""  # Who made the reopen action

                for history in changelog:
                    for item in history.get('items', []):
                        if item.get('field') == 'status':
                            from_status = item.get('fromString', '').lower()
                            to_status = item.get('toString', '').lower()

                            # Check if this transition matches our definition of "reopened"
                            # That is, moving from a reviewing status back to an earlier status
                            # Using the CHANGED FROM ... TO logic as per JIRA JQL syntax
                            if any(review_status in from_status for review_status in from_states) and \
                                    any(early_status in to_status for early_status in to_states):
                                was_reopened = True
                                reopen_time = history.get('created')
                                from_status_value = item.get('fromString', '')
                                to_status_value = item.get('toString', '')

                                # Get who performed the status change (reopen action)
                                if 'author' in history:
                                    reopen_by = history.get('author', {}).get('displayName', 'Unknown')

                                logger.info(
                                    f"Found reopened bug {issue_key}: {from_status} → {to_status} by {reopen_by}")
                                break

                    if was_reopened:
                        break

                if was_reopened:
                    bug['was_reopened'] = True
                    bug['reopen_time'] = reopen_time
                    bug['reopen_from'] = from_status_value
                    bug['reopen_to'] = to_status_value
                    bug['reopen_by'] = reopen_by  # Store who reopened it
                    reopened_bugs.append(bug)

            logger.info(f"Found {len(reopened_bugs)} reopened bugs out of {len(all_bugs)} bugs")

            # Removed cache setting for reopened bugs result
            return reopened_bugs

        except Exception as e:
            logger.error(f"Error searching for reopened bugs: {str(e)}")
            return []

    def find_reopened_bugs(self, project_keys):
        """
        Find bugs that have been reopened across multiple projects
        """
        if not isinstance(project_keys, list):
            project_keys = [project_keys]

        all_reopened_bugs = []
        for project_key in project_keys:
            logger.info(f"Checking project {project_key} for reopened bugs")
            project_reopened_bugs = self.find_reopened_bugs_by_jql(project_key)
            all_reopened_bugs.extend(project_reopened_bugs)

        logger.info(f"Total reopened bugs across all projects: {len(all_reopened_bugs)}")
        return all_reopened_bugs
