"""Layouts the user draws on the layout page (media/custom_layout.py)."""

import logging
import math

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth_headers import resolve_authenticated_user_id
from ...config import get_config
from ...database import get_db
from ...media.custom_layout import normalize_layout_spec
from ...media.layout_preview import PreviewError, preview_clip, preview_frame
from ...repositories.layout_preset_repository import (
    MAX_PRESETS_PER_USER,
    LayoutPresetRepository,
)
from ...utils.async_helpers import run_in_thread

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/layouts", tags=["layouts"])


async def _user_id(request: Request, db: AsyncSession) -> str:
    return await resolve_authenticated_user_id(request, db, get_config())


async def _read_preset(request: Request) -> tuple:
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Body must be JSON") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    name = str(payload.get("name") or "").strip()
    if not 1 <= len(name) <= 80:
        raise HTTPException(status_code=422, detail="Name must be 1 to 80 characters")
    try:
        spec = normalize_layout_spec(payload.get("spec"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return name, spec


@router.get("/")
async def list_layouts(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _user_id(request, db)
    return {"layouts": await LayoutPresetRepository.list_presets(db, user_id)}


@router.post("/")
async def create_layout(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _user_id(request, db)
    name, spec = await _read_preset(request)
    if await LayoutPresetRepository.count_presets(db, user_id) >= MAX_PRESETS_PER_USER:
        raise HTTPException(
            status_code=409, detail=f"You can save up to {MAX_PRESETS_PER_USER} layouts"
        )
    return {"layout": await LayoutPresetRepository.create_preset(db, user_id, name, spec)}


@router.put("/{layout_id}")
async def update_layout(layout_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _user_id(request, db)
    name, spec = await _read_preset(request)
    updated = await LayoutPresetRepository.update_preset(db, user_id, layout_id, name, spec)
    if not updated:
        raise HTTPException(status_code=404, detail="Layout not found")
    return {"layout": updated}


@router.delete("/{layout_id}")
async def delete_layout(layout_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _user_id(request, db)
    if not await LayoutPresetRepository.delete_preset(db, user_id, layout_id):
        raise HTTPException(status_code=404, detail="Layout not found")
    return {"message": "Layout deleted"}


@router.post("/preview")
async def layout_preview(request: Request, db: AsyncSession = Depends(get_db)):
    """A still frame of a YouTube link, as a JPEG."""
    await _user_id(request, db)
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Body must be JSON") from None
    url = payload.get("url") if isinstance(payload, dict) else None
    seconds = payload.get("time", 0) if isinstance(payload, dict) else 0
    if not isinstance(url, str) or isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise HTTPException(status_code=422, detail="url and a numeric time are required")
    if not math.isfinite(seconds) or not 0 <= seconds <= 60 * 60 * 24:
        raise HTTPException(status_code=422, detail="time is out of range")
    try:
        frame = await run_in_thread(preview_frame, url, float(seconds))
    except PreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return Response(content=frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/preview-clip")
async def layout_preview_clip(request: Request, db: AsyncSession = Depends(get_db)):
    """Five seconds of a YouTube link, as an MP4."""
    await _user_id(request, db)
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Body must be JSON") from None
    url = payload.get("url") if isinstance(payload, dict) else None
    seconds = payload.get("time", 0) if isinstance(payload, dict) else 0
    if not isinstance(url, str) or isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise HTTPException(status_code=422, detail="url and a numeric time are required")
    if not math.isfinite(seconds) or not 0 <= seconds <= 60 * 60 * 24:
        raise HTTPException(status_code=422, detail="time is out of range")
    try:
        frame = await run_in_thread(preview_clip, url, float(seconds))
    except PreviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return Response(content=frame, media_type="video/mp4", headers={"Cache-Control": "no-store"})
