from dataclasses import dataclass
from uuid import UUID

from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.access_control import repository
from app.core.access_control.model import OrganizationAccessGroup
from app.core.module_registry.definitions import ModuleDefinition
from app.core.module_registry.registry import ModuleRegistry
from app.core.organization_context.context import OrganizationContext
from app.core.organization_modules import repository as module_repository


class AccessGroupNotFoundError(Exception):
    pass


class AccessGroupConflictError(Exception):
    pass


class InvalidPermissionError(Exception):
    pass


class MembershipAssignmentError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class AccessGroupDetails:
    group: OrganizationAccessGroup
    permission_keys: list[str]
    membership_ids: list[UUID]


@dataclass(frozen=True, slots=True)
class EffectiveAccess:
    is_owner: bool
    enabled_module_keys: tuple[str, ...]
    permission_keys: tuple[str, ...]


def _is_group_name_unique_violation(error: IntegrityError) -> bool:
    return (
        isinstance(error.orig, UniqueViolation)
        and error.orig.diag.constraint_name
        == "uq_organization_access_groups_organization_name"
    )


def _get_group(
    session: Session,
    *,
    organization_id: UUID,
    access_group_id: UUID,
    for_update: bool = False,
) -> OrganizationAccessGroup:
    group = repository.get_access_group(
        session,
        organization_id=organization_id,
        access_group_id=access_group_id,
        for_update=for_update,
    )
    if group is None:
        raise AccessGroupNotFoundError
    return group


def _details(session: Session, group: OrganizationAccessGroup) -> AccessGroupDetails:
    return AccessGroupDetails(
        group=group,
        permission_keys=repository.list_group_permission_keys(session, group.id),
        membership_ids=repository.list_group_membership_ids(session, group.id),
    )


def list_access_groups(
    session: Session, organization_id: UUID
) -> list[OrganizationAccessGroup]:
    return repository.list_access_groups(session, organization_id)


def create_access_group(
    session: Session,
    *,
    organization_id: UUID,
    name: str,
    description: str | None,
) -> OrganizationAccessGroup:
    group = repository.add_access_group(
        session,
        organization_id=organization_id,
        name=name,
        description=description,
    )
    try:
        session.commit()
        session.refresh(group)
        return group
    except IntegrityError as error:
        session.rollback()
        if _is_group_name_unique_violation(error):
            raise AccessGroupConflictError from error
        raise


def get_access_group_details(
    session: Session, *, organization_id: UUID, access_group_id: UUID
) -> AccessGroupDetails:
    return _details(
        session,
        _get_group(
            session,
            organization_id=organization_id,
            access_group_id=access_group_id,
        ),
    )


def update_access_group(
    session: Session,
    *,
    organization_id: UUID,
    access_group_id: UUID,
    name: str | None,
    description: str | None,
    description_is_set: bool,
) -> OrganizationAccessGroup:
    group = _get_group(
        session,
        organization_id=organization_id,
        access_group_id=access_group_id,
        for_update=True,
    )
    if name is not None:
        group.name = name
    if description_is_set:
        group.description = description
    try:
        session.commit()
        session.refresh(group)
        return group
    except IntegrityError as error:
        session.rollback()
        if _is_group_name_unique_violation(error):
            raise AccessGroupConflictError from error
        raise


def delete_access_group(
    session: Session, *, organization_id: UUID, access_group_id: UUID
) -> None:
    group = _get_group(
        session,
        organization_id=organization_id,
        access_group_id=access_group_id,
        for_update=True,
    )
    try:
        session.delete(group)
        session.commit()
    except Exception:
        session.rollback()
        raise


def replace_access_group_permissions(
    session: Session,
    *,
    organization_id: UUID,
    access_group_id: UUID,
    permission_keys: list[str],
    registry: ModuleRegistry,
) -> AccessGroupDetails:
    unique_keys = sorted(set(permission_keys))
    if any(registry.get_permission(key) is None for key in unique_keys):
        raise InvalidPermissionError
    group = _get_group(
        session,
        organization_id=organization_id,
        access_group_id=access_group_id,
        for_update=True,
    )
    try:
        repository.replace_group_permissions(
            session,
            access_group_id=group.id,
            permission_keys=unique_keys,
        )
        session.flush()
        details = _details(session, group)
        session.commit()
        return details
    except Exception:
        session.rollback()
        raise


def replace_access_group_memberships(
    session: Session,
    *,
    organization_id: UUID,
    access_group_id: UUID,
    membership_ids: list[UUID],
) -> AccessGroupDetails:
    group = _get_group(
        session,
        organization_id=organization_id,
        access_group_id=access_group_id,
        for_update=True,
    )
    unique_ids = set(membership_ids)
    memberships = repository.get_memberships_in_organization(
        session,
        organization_id=organization_id,
        membership_ids=unique_ids,
    )
    if {membership.id for membership in memberships} != unique_ids:
        session.rollback()
        raise MembershipAssignmentError
    try:
        repository.replace_group_memberships(
            session,
            access_group_id=group.id,
            membership_ids=sorted(unique_ids),
        )
        session.flush()
        details = _details(session, group)
        session.commit()
        return details
    except Exception:
        session.rollback()
        raise


def get_effective_access(
    session: Session,
    *,
    context: OrganizationContext,
    registry: ModuleRegistry,
) -> EffectiveAccess:
    stored_enabled_keys = module_repository.list_enabled_module_keys(
        session, context.organization.id
    )
    enabled_definitions = tuple(
        definition
        for definition in registry.list()
        if definition.key in stored_enabled_keys
    )
    enabled_keys = tuple(definition.key for definition in enabled_definitions)
    is_owner = context.membership.role == "owner"
    if is_owner:
        permissions = sorted(
            permission.key
            for definition in enabled_definitions
            for permission in definition.permissions
        )
    else:
        granted_keys = repository.list_membership_permission_keys(
            session,
            organization_id=context.organization.id,
            membership_id=context.membership.id,
        )
        permissions = sorted(
            key
            for key in granted_keys
            if registry.get_permission(key) is not None
            and key.split(".", maxsplit=1)[0] in enabled_keys
        )
    return EffectiveAccess(
        is_owner=is_owner,
        enabled_module_keys=enabled_keys,
        permission_keys=tuple(permissions),
    )


def list_permission_catalog(
    session: Session,
    *,
    organization_id: UUID,
    registry: ModuleRegistry,
) -> list[tuple[ModuleDefinition, bool]]:
    enabled_keys = module_repository.list_enabled_module_keys(session, organization_id)
    return [
        (definition, definition.key in enabled_keys)
        for definition in registry.list()
    ]
