"""Automations: streamers, their followed channels and their new videos waiting for approval (channel_watch.py)."""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth_headers import resolve_authenticated_user_id
from ...channel_watch import ChannelWatchService, WatchError
from ...config import get_config
from ...database import get_db

router = APIRouter(prefix="/automations", tags=["automations"])


async def _user_id(request: Request, db: AsyncSession) -> str:
    return await resolve_authenticated_user_id(request, db, get_config())


async def _body(request: Request) -> Dict[str, Any]:
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Body must be JSON") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Body must be an object")
    return payload


def _flag(payload: Dict[str, Any], key: str) -> bool | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise HTTPException(status_code=422, detail=f"{key} must be true or false")
    return value


@router.get("/streamers")
async def list_streamers(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _user_id(request, db)
    return {"streamers": await ChannelWatchService.list_streamers(db, user_id)}


@router.post("/streamers")
async def add_streamer(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _user_id(request, db)
    name = (await _body(request)).get("name")
    if not isinstance(name, str):
        raise HTTPException(status_code=422, detail="name is required")
    try:
        return {"streamer": await ChannelWatchService.add_streamer(db, user_id, name)}
    except WatchError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.delete("/streamers/{streamer_id}")
async def delete_streamer(streamer_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _user_id(request, db)
    if not await ChannelWatchService.delete_streamer(db, user_id, streamer_id):
        raise HTTPException(status_code=404, detail="Streamer not found")
    return {"message": "Streamer removed"}


@router.get("/channels")
async def list_channels(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _user_id(request, db)
    return {"channels": await ChannelWatchService.list_watches(db, user_id)}


@router.post("/channels")
async def add_channel(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _user_id(request, db)
    payload = await _body(request)
    url = payload.get("url")
    if not isinstance(url, str):
        raise HTTPException(status_code=422, detail="url is required")
    streamer_id = payload.get("streamer_id")
    if not isinstance(streamer_id, str) or not streamer_id:
        raise HTTPException(status_code=422, detail="streamer_id is required")
    try:
        channel = await ChannelWatchService.add_watch(
            db, user_id, url, _flag(payload, "allows_clips") or False, streamer_id
        )
    except WatchError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {"channel": channel}


@router.patch("/channels/{channel_id}")
async def update_channel(channel_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _user_id(request, db)
    payload = await _body(request)
    changes = {key: value for key in ("allows_clips", "active") if (value := _flag(payload, key)) is not None}
    channel = await ChannelWatchService.update_watch(db, user_id, channel_id, changes)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return {"channel": channel}


@router.delete("/channels/{channel_id}")
async def delete_channel(channel_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _user_id(request, db)
    if not await ChannelWatchService.delete_watch(db, user_id, channel_id):
        raise HTTPException(status_code=404, detail="Channel not found")
    return {"message": "Channel removed"}


@router.post("/channels/{channel_id}/check")
async def check_channel(channel_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _user_id(request, db)
    try:
        return await ChannelWatchService.check_watch(db, user_id, channel_id)
    except WatchError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.get("/discoveries")
async def list_discoveries(request: Request, status: str = "pending", db: AsyncSession = Depends(get_db)):
    user_id = await _user_id(request, db)
    if status not in {"pending", "approved", "dismissed"}:
        raise HTTPException(status_code=422, detail="status must be pending, approved or dismissed")
    return {"discoveries": await ChannelWatchService.list_discoveries(db, user_id, status)}


@router.post("/discoveries/{discovery_id}/approve")
async def approve_discovery(discovery_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Record the task the frontend created for this video (the task goes through the normal checks)."""
    user_id = await _user_id(request, db)
    task_id = (await _body(request)).get("task_id")
    if not isinstance(task_id, str) or not 0 < len(task_id) <= 36:
        raise HTTPException(status_code=422, detail="task_id is required")
    if not await ChannelWatchService.resolve_discovery(db, user_id, discovery_id, "approved", task_id):
        raise HTTPException(status_code=404, detail="Nothing waiting for approval here")
    return {"message": "Approved"}


@router.post("/discoveries/{discovery_id}/dismiss")
async def dismiss_discovery(discovery_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _user_id(request, db)
    if not await ChannelWatchService.resolve_discovery(db, user_id, discovery_id, "dismissed"):
        raise HTTPException(status_code=404, detail="Nothing waiting for approval here")
    return {"message": "Dismissed"}
