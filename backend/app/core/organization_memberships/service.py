from uuid import UUID

from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.organization_memberships import repository
from app.core.organization_memberships.model import OrganizationMembership
from app.core.organizations import service as organization_service
from app.core.users import service as user_service


class MembershipNotFoundError(Exception):
    pass


class MembershipConflictError(Exception):
    pass


class MembershipAccessDeniedError(Exception):
    pass


class LastOwnerError(Exception):
    pass


def _is_membership_unique_violation(error: IntegrityError) -> bool:
    return (
        isinstance(error.orig, UniqueViolation)
        and error.orig.diag.constraint_name
        == "uq_organization_memberships_user_organization"
    )


def create_membership(
    session: Session,
    *,
    organization_id: UUID,
    user_id: UUID,
    role: str,
    current_user_id: UUID,
) -> OrganizationMembership:
    organization_service.get_organization_for_update(session, organization_id)
    current_membership = repository.get_membership_for_user_organization(
        session,
        user_id=current_user_id,
        organization_id=organization_id,
    )
    if current_membership is None or current_membership.role == "member":
        raise MembershipAccessDeniedError
    if current_membership.role == "admin" and role == "owner":
        raise MembershipAccessDeniedError
    user_service.get_user(session, user_id)

    try:
        return repository.create_membership(
            session,
            user_id=user_id,
            organization_id=organization_id,
            role=role,
        )
    except IntegrityError as error:
        session.rollback()
        if _is_membership_unique_violation(error):
            raise MembershipConflictError from error
        raise


def list_organization_memberships(
    session: Session, organization_id: UUID
) -> list[OrganizationMembership]:
    return repository.list_organization_memberships(session, organization_id)


def list_user_memberships(
    session: Session, user_id: UUID, current_user_id: UUID
) -> list[OrganizationMembership]:
    if user_id != current_user_id:
        raise MembershipAccessDeniedError
    user_service.get_user(session, user_id)
    return repository.list_user_memberships(session, user_id)


def update_membership_role(
    session: Session,
    *,
    organization_id: UUID,
    membership_id: UUID,
    role: str,
    current_user_id: UUID,
) -> OrganizationMembership:
    organization_service.get_organization_for_update(session, organization_id)
    current_membership = repository.get_membership_for_user_organization(
        session,
        user_id=current_user_id,
        organization_id=organization_id,
    )
    if current_membership is None or current_membership.role == "member":
        raise MembershipAccessDeniedError
    membership = repository.get_membership(
        session,
        membership_id=membership_id,
        organization_id=organization_id,
    )
    if membership is None:
        raise MembershipNotFoundError
    if current_membership.role == "admin" and (
        membership.role == "owner" or role == "owner"
    ):
        raise MembershipAccessDeniedError
    if (
        membership.role == "owner"
        and role != "owner"
        and repository.count_organization_owners(session, organization_id) == 1
    ):
        raise LastOwnerError
    return repository.update_membership_role(session, membership, role)
