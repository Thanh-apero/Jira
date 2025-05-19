from jira.core import JiraCore
from jira.issues import IssueHandler
from jira.projects import ProjectHandler
from jira.sprints import SprintHandler
from jira.versions import VersionHandler
from jira.statistics import StatisticsHandler


class JiraAPI:
    """
    Main Jira API class that combines all functionality from specialized modules.
    Acts as a facade for all the handlers.
    """

    def __init__(self, jira_url=None, jira_email=None, jira_token=None):
        self.core = JiraCore(jira_url, jira_email, jira_token)
        self.issues = IssueHandler(self.core)
        self.projects = ProjectHandler(self.core)
        self.sprints = SprintHandler(self.core)
        self.versions = VersionHandler(self.core)
        self.statistics = StatisticsHandler(self.core)

    # Core functionality proxies
    @property
    def jira_url(self):
        return self.core.jira_url

    @property
    def jira_email(self):
        return self.core.jira_email

    @property
    def jira_token(self):
        return self.core.jira_token

    @property
    def auth(self):
        return self.core.auth

    def is_configured(self):
        return self.core.is_configured()

    # Proxy methods to appropriate handlers
    # Issue methods
    def get_issue_types(self):
        return self.core.get_issue_types()

    def get_available_statuses(self):
        return self.core.get_available_statuses()

    def get_issue_with_changelog(self, issue_key, use_cache=True, fields=None):
        return self.issues.get_issue_with_changelog(issue_key, use_cache, fields)

    def search_issues(self, jql, fields=None, max_results=50, expand=None, use_cache=True, expiry=None):
        return self.issues.search_issues(jql, fields, max_results, expand, use_cache, expiry)

    def find_new_issues(self, project_keys, hours=1):
        return self.issues.find_new_issues(project_keys, hours)

    def find_status_changes(self, project_keys, hours=1):
        return self.issues.find_status_changes(project_keys, hours)

    def find_new_comments(self, project_keys, hours=1):
        return self.issues.find_new_comments(project_keys, hours)

    def find_overdue_issues(self, project_keys):
        return self.issues.find_overdue_issues(project_keys)

    def find_upcoming_deadlines(self, project_keys, days=3):
        return self.issues.find_upcoming_deadlines(project_keys, days)

    def create_issue(self, project_key, issue_data):
        return self.issues.create_issue(project_key, issue_data)

    def update_issue(self, issue_key, update_data):
        return self.issues.update_issue(issue_key, update_data)

    # Project methods
    def get_all_projects(self, use_cache=True):
        return self.projects.get_all_projects(use_cache)

    def get_project_participants(self, project_key):
        return self.projects.get_project_participants(project_key)

    def get_project_category(self, project_id):
        return self.projects.get_project_category(project_id)

    # Version methods
    def get_project_versions(self, project_key):
        return self.versions.get_project_versions(project_key)

    def get_issues_by_version(self, project_key, version_id):
        return self.versions.get_issues_by_version(project_key, version_id)

    # Sprint methods
    def get_active_sprints(self, project_key, use_cache=True):
        return self.sprints.get_active_sprints(project_key, use_cache)

    def add_issue_to_sprint(self, sprint_id, issue_key):
        return self.sprints.add_issue_to_sprint(sprint_id, issue_key)

    # Statistics methods
    def get_project_statistics(self, project_key, start_date=None, end_date=None, participant=None):
        return self.statistics.get_project_statistics(project_key, start_date, end_date, participant)

    def find_reopened_bugs(self, project_keys):
        return self.statistics.find_reopened_bugs(project_keys)

    def find_reopened_bugs_by_jql(self, project_key, start_date=None, end_date=None, participant=None):
        return self.statistics.find_reopened_bugs_by_jql(project_key, start_date, end_date, participant)

    def test_get_status_transitions(self, project_key, limit=10):
        return self.statistics.test_get_status_transitions(project_key, limit)

    # Custom fields methods
    def find_custom_fields(self):
        return self.core.find_custom_fields()

    def get_field_id_by_name(self, field_name_to_find):
        return self.core.get_field_id_by_name(field_name_to_find)

    def find_epic_by_name(self, project_key, epic_name):
        return self.issues.find_epic_by_name(project_key, epic_name)

    # Notification history methods
    def mark_issue_notified(self, issue_type, issue_key, reason=None):
        return self.core.mark_issue_notified(issue_type, issue_key, reason)

    def was_issue_notified(self, issue_type, issue_key):
        return self.core.was_issue_notified(issue_type, issue_key)
