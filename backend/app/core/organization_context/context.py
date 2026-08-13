from dataclasses import dataclass

from app.core.organization_memberships.model import OrganizationMembership
from app.core.organizations.model import Organization
from app.core.users.model import User


@dataclass(frozen=True, slots=True)
class OrganizationContext:
    user: User
    organization: Organization
    membership: OrganizationMembership
