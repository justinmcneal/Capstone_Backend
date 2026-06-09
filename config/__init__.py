"""
Celery app auto-discovery on Django startup
"""

from .celery import app as celery_app

__all__ = ("celery_app",)
