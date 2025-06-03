import logging
import requests

logger = logging.getLogger(__name__)


class ProjectHandler:
    """
    Handles project-related operations such as getting project details,
    categories, and participants.
    """

    def __init__(self, core):
        """Initialize with a JiraCore instance"""
        self.core = core

    def get_all_projects(self, use_cache=True):
        """Get all projects from Jira"""
        cache_key = 'all_projects'

        # Return from cache if valid
        if use_cache and self.core._is_cache_valid(cache_key) and cache_key in self.core._projects_cache:
            logger.info(f"Using cached projects data ({len(self.core._projects_cache[cache_key])} projects)")
            return self.core._projects_cache[cache_key]

        if not self.core.is_configured():
            logger.error("Jira API credentials not configured")
            return []

        try:
            logger.info(f"Fetching projects from {self.core.jira_url}/rest/api/2/project")
            response = requests.get(
                f"{self.core.jira_url}/rest/api/2/project",
                auth=self.core.auth
            )

            if response.status_code == 200:
                projects = response.json()
                logger.info(f"Successfully fetched {len(projects)} projects from Jira")

                result = []
                # For efficiency, don't make API calls for categories - determine from naming conventions
                for project in projects:
                    key = project.get('key', '')
                    # Determine category from key pattern
                    if key.startswith('BE') or key.startswith('BACKEND'):
                        category = 'Backend'
                    elif key.startswith('FE') or key.startswith('FRONTEND'):
                        category = 'Frontend'
                    elif key.startswith('MOB') or key.startswith('MOBILE'):
                        category = 'Mobile'
                    elif key.startswith('AIP'):
                        category = 'Software'
                    elif key.startswith('AAIP'):
                        category = 'AI Products'
                    else:
                        category = 'General'

                    result.append({
                        "key": project.get('key'),
                        "name": project.get('name'),
                        "id": project.get('id'),
                        "category": category,
                        "avatarUrl": project.get('avatarUrls', {}).get('48x48', '')
                    })

                logger.info(f"Processed {len(result)} projects with categories")
                # Cache the result
                self.core._set_cache('projects', cache_key, result)
                return result
            else:
                logger.error(f"Failed to fetch projects: {response.status_code}")
                logger.error(f"Response: {response.text}")
                return []
        except Exception as e:
            logger.error(f"Error getting projects: {str(e)}")
            return []

    def get_project_category(self, project_id):
        """
        Get project category from Jira
        This is now only used as a fallback - the main categorization is done in get_all_projects
        """
        if not self.core.is_configured():
            return "Unknown"

        try:
            response = requests.get(
                f"{self.core.jira_url}/rest/api/2/project/{project_id}",
                auth=self.core.auth
            )

            if response.status_code == 200:
                project_data = response.json()
                # Try to get category from project data
                if 'projectCategory' in project_data and project_data['projectCategory']:
                    return project_data['projectCategory'].get('name', 'General')
                else:
                    # Check for custom field or naming convention that might indicate category
                    key = project_data.get('key', '')
                    # Check naming patterns
                    if key.startswith('BE') or key.startswith('BACKEND'):
                        return 'Backend'
                    elif key.startswith('FE') or key.startswith('FRONTEND'):
                        return 'Frontend'
                    elif key.startswith('MOB') or key.startswith('MOBILE'):
                        return 'Mobile'
                    elif key.startswith('AIP'):
                        return 'Software'
                    elif key.startswith('AAIP'):
                        return 'AI Products'
                    else:
                        # Default category based on URL pattern
                        if '/software/' in self.core.jira_url:
                            return 'Software'
                        else:
                            return 'General'
            else:
                return "Unknown"
        except Exception as e:
            logger.error(f"Error getting project category: {str(e)}")
            return "Unknown"

    def get_project_participants(self, project_key):
        """
        Get all participants (users who have created or commented or been assigned to issues) in a project
        This can be used to populate assignee filters
        """
        if not self.core.is_configured():
            logger.error("Jira API credentials not configured")
            return []

        # Khôi phục kiểm tra cache
        cache_key = f"participants_{project_key}"
        if self.core._is_cache_valid(cache_key) and cache_key in self.core._projects_cache:
            logger.info(f"Using cached participants data for project {project_key}")
            return self.core._projects_cache[cache_key]

        try:
            # OPTIMIZATION: Use a more efficient query with just the fields we need
            # Also limit to recent issues to improve performance
            jql = f'project = {project_key} ORDER BY updated DESC'

            # Import here to avoid circular import
            from jira.issues import IssueHandler
            issue_handler = IssueHandler(self.core)
            issues = issue_handler.search_issues(
                jql,
                fields="assignee,reporter,comment",  # Request assignee, reporter, and comment fields
                max_results=200,  # Reduced from 500 to 200
                use_cache=True,  # Use cache to avoid repeated calls
                expiry=1800  # Cache for 30 minutes
            )

            participants = {}

            # Process all participants (assignees, reporters, and commenters)
            for issue in issues:
                fields = issue.get('fields', {})
                if not fields:
                    continue

                # Process assignee
                assignee = fields.get('assignee')
                if assignee and isinstance(assignee, dict):
                    user_key = assignee.get('key') or assignee.get('accountId')
                    if user_key and user_key not in participants:
                        participants[user_key] = {
                            'key': user_key,
                            'name': assignee.get('displayName', 'Unknown'),
                            'avatarUrl': assignee.get('avatarUrls', {}).get('48x48', ''),
                            'email': assignee.get('emailAddress', ''),
                            'accountId': assignee.get('accountId', ''),
                            'active': assignee.get('active', True),
                            'timeZone': assignee.get('timeZone', ''),
                            'issueCount': 0,
                            'assignedCount': 0,
                            'reportedCount': 0,
                            'commentCount': 0
                        }
                    if user_key in participants:
                        participants[user_key]['assignedCount'] += 1
                        participants[user_key]['issueCount'] += 1
                
                # Process reporter
                reporter = fields.get('reporter')
                if reporter and isinstance(reporter, dict):
                    user_key = reporter.get('key') or reporter.get('accountId')
                    if user_key and user_key not in participants:
                        participants[user_key] = {
                            'key': user_key,
                            'name': reporter.get('displayName', 'Unknown'),
                            'avatarUrl': reporter.get('avatarUrls', {}).get('48x48', ''),
                            'email': reporter.get('emailAddress', ''),
                            'accountId': reporter.get('accountId', ''),
                            'active': reporter.get('active', True),
                            'timeZone': reporter.get('timeZone', ''),
                            'issueCount': 0,
                            'assignedCount': 0,
                            'reportedCount': 0,
                            'commentCount': 0
                        }
                    if user_key in participants:
                        participants[user_key]['reportedCount'] += 1
                        participants[user_key]['issueCount'] += 1
                
                # Process commenters
                comments = fields.get('comment', {}).get('comments', [])
                for comment in comments:
                    author = comment.get('author')
                    if author and isinstance(author, dict):
                        user_key = author.get('key') or author.get('accountId')
                        if user_key and user_key not in participants:
                            participants[user_key] = {
                                'key': user_key,
                                'name': author.get('displayName', 'Unknown'),
                                'avatarUrl': author.get('avatarUrls', {}).get('48x48', ''),
                                'email': author.get('emailAddress', ''),
                                'accountId': author.get('accountId', ''),
                                'active': author.get('active', True),
                                'timeZone': author.get('timeZone', ''),
                                'issueCount': 0,
                                'assignedCount': 0,
                                'reportedCount': 0,
                                'commentCount': 0
                            }
                        if user_key in participants:
                            participants[user_key]['commentCount'] += 1
                            # Don't increment issueCount for comments to avoid double counting

            # Convert dictionary to list and sort by issue count
            result = list(participants.values())
            result.sort(key=lambda x: x['issueCount'], reverse=True)

            # Cache the result
            self.core._set_cache('projects', cache_key, result, expiry=1800)
            logger.info(f"Found {len(result)} participants (assignees) in project {project_key}")
            return result

        except Exception as e:
            logger.error(f"Error getting project participants: {str(e)}")
            return []
