from datetime import UTC, datetime, timedelta

from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.organization_invitations import repository as invitation_repository
from app.core.organizations import repository as organization_repository
from app.core.organizations.model import Organization
from app.core.platform_admin import repository
from app.core.platform_admin.model import PlatformAdmin
from app.core.platform_admin.schemas import PlatformAdminGrant, PlatformOrganizationCreate
from app.core.users import repository as user_repository


class PlatformAdminUserNotFoundError(Exception):
    pass


def _is_platform_admin_unique_violation(error: IntegrityError) -> bool:
    return (
        isinstance(error.orig, UniqueViolation)
        and error.orig.diag.constraint_name == "uq_platform_admins_user_id"
    )


def grant_platform_admin(
    session: Session, email: str
) -> tuple[PlatformAdmin, bool]:
    grant = PlatformAdminGrant(email=email)
    user = user_repository.get_user_by_email(session, str(grant.email))
    if user is None:
        raise PlatformAdminUserNotFoundError

    existing = repository.get_platform_admin_by_user_id(session, user.id)
    if existing is not None:
        return existing, False

    platform_admin = repository.add_platform_admin(session, user.id)
    try:
        session.commit()
        session.refresh(platform_admin)
    except IntegrityError as error:
        session.rollback()
        if not _is_platform_admin_unique_violation(error):
            raise
        existing = repository.get_platform_admin_by_user_id(session, user.id)
        if existing is None:
            raise
        return existing, False
    return platform_admin, True


def list_organizations(
    session: Session, *, limit: int, offset: int
) -> list[Organization]:
    return organization_repository.list_all_organizations(session, limit, offset)


def provision_organization(
    session: Session, payload: PlatformOrganizationCreate
) -> Organization:
    expires_at = datetime.now(UTC) + timedelta(hours=168)
    try:
        organization = organization_repository.add_organization(
            session, payload.name
        )
        session.flush()
        invitation_repository.add_invitations(
            session,
            organization_id=organization.id,
            emails=[str(email) for email in payload.invitation_emails],
            expires_at=expires_at,
        )
        session.commit()
        session.refresh(organization)
        return organization
    except Exception:
        session.rollback()
        raise
