# Jira API Package

This package provides a modular implementation of the Jira API client used in the Jira Discord Notifier application.

## Structure

The package is organized into the following modules:

- `__init__.py` - Imports and exposes the main JiraAPI class
- `core.py` - Contains the JiraCore class with basic API functionality and caching
- `issues.py` - Contains IssueHandler for issue-related operations
- `projects.py` - Contains ProjectHandler for project-related operations
- `sprints.py` - Contains SprintHandler for sprint-related operations
- `versions.py` - Contains VersionHandler for version-related operations
- `statistics.py` - Contains StatisticsHandler for statistics and reporting
- `utils.py` - Contains utility functions for dates, JQL filters, etc.

## Usage

Import the JiraAPI class from the package:

```python
from jira import JiraAPI

# Initialize with explicit credentials
jira_api = JiraAPI(
    jira_url="https://your-instance.atlassian.net",
    jira_email="your-email@example.com",
    jira_token="your-api-token"
)

# Or use environment variables (JIRA_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN)
jira_api = JiraAPI()

# Check if configured correctly
if jira_api.is_configured():
    # Use API methods
    projects = jira_api.get_all_projects()
    print(f"Found {len(projects)} projects")
```

## Advanced Usage

For more advanced usage, you can access the specialized handlers directly:

```python
# Get project statistics
stats = jira_api.statistics.get_project_statistics("PROJECT")

# Find reopened bugs
bugs = jira_api.statistics.find_reopened_bugs(["PROJECT1", "PROJECT2"])

# Work with sprints
sprints = jira_api.sprints.get_active_sprints("PROJECT")
jira_api.sprints.add_issue_to_sprint(sprint_id, issue_key)

# Work with versions
versions = jira_api.versions.get_project_versions("PROJECT")
```

## Caching

The API includes a caching mechanism to reduce API calls to Jira. Most methods have cache parameters to control caching
behavior:

- `use_cache=True` - Use cached results if available (default)
- `expiry=None` - Override the default cache expiration time (in seconds)

## Error Handling

All API methods include robust error handling and logging. Errors are logged using the standard Python logging
mechanism.