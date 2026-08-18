from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OrganizationAccessGroup(Base):
    __tablename__ = "organization_access_groups"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_organization_access_groups_organization_name",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "organizations.id",
            name="fk_organization_access_groups_organization_id",
        ),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class OrganizationAccessGroupPermission(Base):
    __tablename__ = "organization_access_group_permissions"
    __table_args__ = (
        UniqueConstraint(
            "access_group_id",
            "permission_key",
            name="uq_organization_access_group_permissions_group_permission",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    access_group_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "organization_access_groups.id",
            name="fk_organization_access_group_permissions_group_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    permission_key: Mapped[str] = mapped_column(String(255), nullable=False)


class OrganizationMembershipAccessGroup(Base):
    __tablename__ = "organization_membership_access_groups"
    __table_args__ = (
        UniqueConstraint(
            "organization_membership_id",
            "access_group_id",
            name="uq_organization_membership_access_groups_membership_group",
        ),
        Index(
            "ix_organization_membership_access_groups_access_group_id",
            "access_group_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_membership_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "organization_memberships.id",
            name="fk_organization_membership_access_groups_membership_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    access_group_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "organization_access_groups.id",
            name="fk_organization_membership_access_groups_group_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
