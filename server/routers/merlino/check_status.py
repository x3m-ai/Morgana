"""
Merlino router: GET /api/v2/merlino/check_status

Lightweight liveness probe for the Merlino Settings panel.
Returns {"status": "ok"} when Morgana is up and the API key is valid.
"""

import logging

from fastapi import APIRouter, Depends

from config import settings
from core.auth import require_api_key

log = logging.getLogger("morgana.router.check_status")

router = APIRouter()


@router.get("/check_status")
async def check_status(_: str = Depends(require_api_key)):
    """Return ok if Morgana is running and the supplied API key is valid."""
    log.info("[CHECK_STATUS] OK")
    return {"status": "ok", "version": settings.version}
