"""Layout presets: the layouts a user drew on the layout page."""

import json
import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

MAX_PRESETS_PER_USER = 30


class LayoutPresetRepository:
    @staticmethod
    def _serialize(row: Any) -> Dict[str, Any]:
        spec = row.spec
        return {
            "id": row.id,
            "name": row.name,
            "spec": json.loads(spec) if isinstance(spec, str) else spec,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    @staticmethod
    async def list_presets(db: AsyncSession, user_id: str) -> List[Dict[str, Any]]:
        result = await db.execute(
            text(
                "SELECT id, name, spec, created_at, updated_at FROM layout_presets "
                "WHERE user_id = :user_id ORDER BY created_at DESC"
            ),
            {"user_id": user_id},
        )
        return [LayoutPresetRepository._serialize(row) for row in result.fetchall()]

    @staticmethod
    async def get_preset(db: AsyncSession, user_id: str, preset_id: str) -> Optional[Dict[str, Any]]:
        result = await db.execute(
            text(
                "SELECT id, name, spec, created_at, updated_at FROM layout_presets "
                "WHERE id = :id AND user_id = :user_id"
            ),
            {"id": preset_id, "user_id": user_id},
        )
        row = result.fetchone()
        return LayoutPresetRepository._serialize(row) if row else None

    @staticmethod
    async def count_presets(db: AsyncSession, user_id: str) -> int:
        result = await db.execute(
            text("SELECT COUNT(*) FROM layout_presets WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        return int(result.scalar() or 0)

    @staticmethod
    async def create_preset(
        db: AsyncSession, user_id: str, name: str, spec: Dict[str, Any]
    ) -> Dict[str, Any]:
        result = await db.execute(
            text(
                "INSERT INTO layout_presets (id, user_id, name, spec) "
                "VALUES (:id, :user_id, :name, CAST(:spec AS JSONB)) "
                "RETURNING id, name, spec, created_at, updated_at"
            ),
            {"id": str(uuid4()), "user_id": user_id, "name": name, "spec": json.dumps(spec)},
        )
        row = result.fetchone()
        await db.commit()
        return LayoutPresetRepository._serialize(row)

    @staticmethod
    async def update_preset(
        db: AsyncSession, user_id: str, preset_id: str, name: str, spec: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        result = await db.execute(
            text(
                "UPDATE layout_presets SET name = :name, spec = CAST(:spec AS JSONB), "
                "updated_at = CURRENT_TIMESTAMP WHERE id = :id AND user_id = :user_id "
                "RETURNING id, name, spec, created_at, updated_at"
            ),
            {"id": preset_id, "user_id": user_id, "name": name, "spec": json.dumps(spec)},
        )
        row = result.fetchone()
        await db.commit()
        return LayoutPresetRepository._serialize(row) if row else None

    @staticmethod
    async def delete_preset(db: AsyncSession, user_id: str, preset_id: str) -> bool:
        result = await db.execute(
            text("DELETE FROM layout_presets WHERE id = :id AND user_id = :user_id"),
            {"id": preset_id, "user_id": user_id},
        )
        await db.commit()
        return bool(result.rowcount)
