import os
import logging
import pickle
import threading
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

# File to store project settings
PROJECT_SETTINGS_FILE = "project_settings.pkl"

# Create a lock for thread safety
settings_lock = threading.Lock()


class ProjectManager:
    def __init__(self):
        """Initialize project manager and load saved settings"""
        self.watched_projects = {}
        self.project_categories = {}
        self.project_webhooks = {}
        self.load_settings()

    def load_settings(self):
        """Load project settings from pickle file"""
        if Path(PROJECT_SETTINGS_FILE).exists():
            try:
                with open(PROJECT_SETTINGS_FILE, 'rb') as f:
                    data = pickle.load(f)

                    self.watched_projects = data.get('watched_projects', {})
                    self.project_categories = data.get('project_categories', {})
                    self.project_webhooks = data.get('project_webhooks', {})
            except Exception as e:
                logger.error(f"Error loading project settings: {str(e)}")
                self.watched_projects = {}
                self.project_categories = {}
                self.project_webhooks = {}
        else:
            self.watched_projects = {}
            self.project_categories = {}
            self.project_webhooks = {}

    def save_settings(self):
        """Save project settings to pickle file"""
        with settings_lock:
            data = {
                'watched_projects': self.watched_projects,
                'project_categories': self.project_categories,
                'project_webhooks': self.project_webhooks,
            }

            try:
                with open(PROJECT_SETTINGS_FILE, 'wb') as f:
                    pickle.dump(data, f)
                logger.info("Project settings saved successfully")
            except Exception as e:
                logger.error(f"Error saving project settings: {str(e)}")

    def toggle_project_watch(self, project_key, project_name=None):
        """Toggle watching status for a project"""
        if project_key in self.watched_projects:
            # Unwatch project
            del self.watched_projects[project_key]
            status = "unwatched"
        else:
            # Watch project
            self.watched_projects[project_key] = {
                'name': project_name or project_key,
                'added_at': datetime.now().isoformat()
            }
            status = "watched"

        # Save settings
        self.save_settings()
        return status

    def update_project_webhook(self, project_key, webhook_url):
        """Update Discord webhook URL for a specific project"""
        if webhook_url:
            self.project_webhooks[project_key] = webhook_url
        elif project_key in self.project_webhooks:
            # Remove webhook if empty URL provided
            del self.project_webhooks[project_key]

        # Save settings
        self.save_settings()

    def get_project_webhook(self, project_key, default_webhook=None):
        """Get project-specific webhook URL or default"""
        return self.project_webhooks.get(project_key, default_webhook)

    def update_project_categories(self, projects):
        """
        Update project categories based on project data
        
        Args:
            projects (list): List of project dictionaries with keys 'key', 'category'
        """
        for project in projects:
            key = project.get('key')
            category = project.get('category')

            if key and category:
                self.project_categories[key] = category

        # Save settings
        self.save_settings()

    def get_watched_projects_by_category(self):
        """Group watched projects by category"""
        categories = {}

        for project_key, project_data in self.watched_projects.items():
            category = self.project_categories.get(project_key, 'General')

            if category not in categories:
                categories[category] = []

            categories[category].append({
                'key': project_key,
                'name': project_data.get('name', project_key),
                'webhook': self.get_project_webhook(project_key),
                'added_at': project_data.get('added_at')
            })

        return categories

    def get_all_projects_by_category(self, projects):
        """
        Group all projects by category
        
        Args:
            projects (list): List of project dictionaries
        """
        # Update project categories first
        logger.info(f"Grouping {len(projects)} projects by category")
        self.update_project_categories(projects)

        categories = {}

        for project in projects:
            key = project.get('key')
            category = self.project_categories.get(key, 'General')

            if category not in categories:
                categories[category] = []

            is_watched = key in self.watched_projects

            categories[category].append({
                'key': key,
                'name': project.get('name', key),
                'id': project.get('id'),
                'watched': is_watched,
                'webhook': self.get_project_webhook(key),
                'avatarUrl': project.get('avatarUrl', '')
            })

        logger.info(f"Created {len(categories)} categories: {list(categories.keys())}")
        for category, projs in categories.items():
            logger.info(f"Category '{category}' has {len(projs)} projects")

        return categories

    def get_watched_project_keys(self):
        """Get list of watched project keys"""
        return list(self.watched_projects.keys())

    def is_project_watched(self, project_key):
        """Check if project is being watched"""
        return project_key in self.watched_projects
