# core/utils/celery_helpers.py
from django.conf import settings

def run_task(task, *args, **kwargs):
    """
    Run a Celery task either asynchronously (if worker exists)
    or synchronously (for free tier without workers).
    """
    if getattr(settings, "FREE_TIER", False):
        # Call the underlying run directly, skipping Celery
        # task.run is the raw Python run for the task
        return task.run(*args, **kwargs)
    else:
        # Run async via Celery worker
        return task.delay(*args, **kwargs)