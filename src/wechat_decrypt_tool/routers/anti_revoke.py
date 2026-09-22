from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..anti_revoke_service import (
    get_anti_revoke_config,
    get_anti_revoke_sessions,
    install_anti_revoke_triggers,
    set_anti_revoke_config,
    uninstall_anti_revoke_triggers,
)
from ..logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/anti_revoke", tags=["anti_revoke"])


class AntiRevokeBatchRequest(BaseModel):
    account: str = Field(..., description="Account identifier")
    session_ids: List[str] = Field(..., description="List of session usernames to install/uninstall triggers")


class AntiRevokeConfigRequest(BaseModel):
    account: str = Field(..., description="Account identifier")
    auto_apply: bool = Field(..., description="Whether to automatically install triggers for new group chats")


@router.get("/sessions")
async def api_get_anti_revoke_sessions(account: str = Query(..., description="Account identifier")):
    """Get all candidate chat sessions and their anti-revoke status."""
    try:
        data = get_anti_revoke_sessions(account)
        return data
    except Exception as exc:
        logger.exception(f"Failed to get anti-revoke sessions for {account}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/install")
async def api_install_anti_revoke_triggers(req: AntiRevokeBatchRequest):
    """Install anti-revoke triggers for the specified sessions."""
    try:
        data = install_anti_revoke_triggers(req.account, req.session_ids)
        return data
    except Exception as exc:
        logger.exception(f"Failed to install anti-revoke triggers for {req.account}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/uninstall")
async def api_uninstall_anti_revoke_triggers(req: AntiRevokeBatchRequest):
    """Uninstall anti-revoke triggers for the specified sessions."""
    try:
        data = uninstall_anti_revoke_triggers(req.account, req.session_ids)
        return data
    except Exception as exc:
        logger.exception(f"Failed to uninstall anti-revoke triggers for {req.account}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/config")
async def api_get_anti_revoke_config(account: str = Query(..., description="Account identifier")):
    """Get anti-revoke configuration for account."""
    try:
        return get_anti_revoke_config(account)
    except Exception as exc:
        logger.exception(f"Failed to get anti-revoke config for {account}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/config")
async def api_set_anti_revoke_config(req: AntiRevokeConfigRequest):
    """Set anti-revoke configuration for account."""
    try:
        return set_anti_revoke_config(req.account, req.auto_apply)
    except Exception as exc:
        logger.exception(f"Failed to set anti-revoke config for {req.account}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
