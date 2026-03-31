from fastapi import BackgroundTasks

from app.config import get_webhook_dispatch_mode
from app.webhook_worker import process_webhook_job


def _dispatch_webhook_job_local(job, background_tasks: BackgroundTasks | None = None):
    if background_tasks is None:
        process_webhook_job(job)
        return

    background_tasks.add_task(process_webhook_job, job)


def _dispatch_webhook_job_sqs(job):
    raise NotImplementedError(
        "SQS webhook job dispatch is not implemented yet. "
        "Set WEBHOOK_DISPATCH_MODE=local for the current local workflow."
    )


def dispatch_webhook_job(job, background_tasks: BackgroundTasks | None = None):
    dispatch_mode = get_webhook_dispatch_mode()
    if dispatch_mode == "local":
        _dispatch_webhook_job_local(job, background_tasks=background_tasks)
        return

    if dispatch_mode == "sqs":
        _dispatch_webhook_job_sqs(job)
        return

    raise ValueError(f"Unsupported webhook dispatch mode: {dispatch_mode}")
