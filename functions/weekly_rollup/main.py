"""
GCP Cloud Function: weekly_rollup

Triggered by Cloud Scheduler once a week. Calls the Spiritbox admin API's
`POST /api/admin/rollup/weekly` which clusters each user's last 7 days of
entries into themes and persists them in `theme_rollups`.

Environment:
    SPIRITBOX_API_BASE  — e.g. https://api.spiritbox.app
    ADMIN_USERNAME      — basic-auth user
    ADMIN_PASSWORD      — basic-auth pass
"""
import base64
import json
import logging
import os

import functions_framework  # type: ignore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@functions_framework.http
def weekly_rollup(request):
    """Cloud Function entry point — fires the rollup and returns its result."""
    api_base = os.environ.get("SPIRITBOX_API_BASE", "")
    user = os.environ.get("ADMIN_USERNAME", "")
    pwd = os.environ.get("ADMIN_PASSWORD", "")
    if not (api_base and user and pwd):
        msg = "SPIRITBOX_API_BASE / ADMIN_USERNAME / ADMIN_PASSWORD not set"
        logger.error(msg)
        return (msg, 500)

    import requests  # type: ignore

    auth_header = "Basic " + base64.b64encode(f"{user}:{pwd}".encode()).decode()
    url = f"{api_base.rstrip('/')}/api/admin/rollup/weekly"
    try:
        resp = requests.post(
            url,
            headers={"Authorization": auth_header, "Content-Type": "application/json"},
            timeout=300,  # rollups call the LLM; generous budget
        )
    except Exception as exc:
        logger.error(f"Rollup call failed: {exc}")
        return (f"rollup call failed: {exc}", 500)

    if resp.status_code >= 400:
        logger.error(f"Rollup API returned {resp.status_code}: {resp.text[:500]}")
        return (f"rollup API {resp.status_code}", resp.status_code)

    logger.info(f"Rollup completed: {resp.text[:500]}")
    return (
        json.dumps({"status": "ok", "upstream": resp.json()}),
        200,
        {"Content-Type": "application/json"},
    )
