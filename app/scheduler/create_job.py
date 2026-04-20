"""
GCP Cloud Scheduler wrapper for creating one-off reminder jobs.

For local development, job creation is stubbed — details are logged instead
of making a real GCP API call. Set GCP_PROJECT_ID to enable real scheduling.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


def _is_gcp_configured() -> bool:
    return bool(settings.GCP_PROJECT_ID and settings.CLOUD_FUNCTION_URL)


async def create_reminder_job(
    job_name: str,
    schedule_time: datetime,
    payload: dict,
) -> Optional[str]:
    """
    Create a one-off Cloud Scheduler job that fires the reminder Cloud Function.

    For local dev (no GCP_PROJECT_ID set), this logs the job details and
    returns a stub job name.

    Args:
        job_name:      Unique name for the scheduler job (alphanumeric + hyphens).
        schedule_time: UTC datetime when the job should fire.
        payload:       JSON-serialisable dict passed to the Cloud Function.

    Returns:
        Full resource name of the created job, or stub name if local.
    """
    cron_schedule = _datetime_to_cron(schedule_time)

    if not _is_gcp_configured():
        logger.info(
            "[LocalDev] Would create Cloud Scheduler job:\n"
            f"  name      : {job_name}\n"
            f"  schedule  : {cron_schedule} (UTC)\n"
            f"  fire_at   : {schedule_time.isoformat()}\n"
            f"  target_url: {settings.CLOUD_FUNCTION_URL or '<not set>'}\n"
            f"  payload   : {json.dumps(payload)}"
        )
        return f"projects/local/locations/local/jobs/{job_name}"

    # Real GCP path
    try:
        from google.cloud import scheduler_v1  # type: ignore
        from google.protobuf import timestamp_pb2  # type: ignore

        client = scheduler_v1.CloudSchedulerClient()
        parent = f"projects/{settings.GCP_PROJECT_ID}/locations/{settings.GCP_REGION}"

        job = scheduler_v1.Job(
            name=f"{parent}/jobs/{job_name}",
            schedule=cron_schedule,
            time_zone="UTC",
            http_target=scheduler_v1.HttpTarget(
                uri=settings.CLOUD_FUNCTION_URL,
                http_method=scheduler_v1.HttpMethod.POST,
                headers={"Content-Type": "application/json"},
                body=json.dumps(payload).encode("utf-8"),
            ),
        )

        response = client.create_job(parent=parent, job=job)
        logger.info(f"Created Cloud Scheduler job: {response.name}")
        return response.name

    except Exception as e:
        logger.error(f"Failed to create Cloud Scheduler job '{job_name}': {e}", exc_info=True)
        raise


async def delete_reminder_job(job_name: str) -> None:
    """
    Delete a Cloud Scheduler job by name.

    Args:
        job_name: The short job name (without project path prefix).
    """
    if not _is_gcp_configured():
        logger.info(f"[LocalDev] Would delete Cloud Scheduler job: {job_name}")
        return

    try:
        from google.cloud import scheduler_v1  # type: ignore

        client = scheduler_v1.CloudSchedulerClient()
        full_name = (
            f"projects/{settings.GCP_PROJECT_ID}"
            f"/locations/{settings.GCP_REGION}"
            f"/jobs/{job_name}"
        )
        client.delete_job(name=full_name)
        logger.info(f"Deleted Cloud Scheduler job: {full_name}")
    except Exception as e:
        logger.error(f"Failed to delete Cloud Scheduler job '{job_name}': {e}", exc_info=True)
        raise


def _datetime_to_cron(dt: datetime) -> str:
    """Convert a datetime to a UTC cron expression (fires once at that minute)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    utc = dt.astimezone(timezone.utc)
    return f"{utc.minute} {utc.hour} {utc.day} {utc.month} *"
