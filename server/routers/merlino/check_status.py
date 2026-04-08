"""
Merlino router: GET /api/v2/merlino/check_status

Lightweight liveness probe for the Merlino Settings panel.
Returns {"status": "ok"} when Morgana is up and the API key is valid.
"""

import logging

from fastapi import APIRouter, Header, HTTPException

from config import settings

log = logging.getLogger("morgana.router.check_status")

router = APIRouter()


@router.get("/check_status")
async def check_status(key: str = Header(default="")):
    """Return ok if Morgana is running and the supplied API key is valid."""
    if key != settings.api_key:
        log.warning("[CHECK_STATUS] Unauthorized request (bad API key)")
        raise HTTPException(status_code=401, detail="Unauthorized")
    log.info("[CHECK_STATUS] OK")
    return {"status": "ok", "version": settings.version}
