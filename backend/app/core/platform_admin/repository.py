from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.platform_admin.model import PlatformAdmin


def get_platform_admin_by_user_id(
    session: Session, user_id: UUID
) -> PlatformAdmin | None:
    return session.scalar(
        select(PlatformAdmin).where(PlatformAdmin.user_id == user_id)
    )


def add_platform_admin(session: Session, user_id: UUID) -> PlatformAdmin:
    platform_admin = PlatformAdmin(user_id=user_id)
    session.add(platform_admin)
    return platform_admin
