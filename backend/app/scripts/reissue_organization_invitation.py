import argparse
from collections.abc import Sequence
from uuid import UUID

from pydantic import ValidationError

from app.core.organization_invitations import service
from app.database import SessionLocal


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reissue an expired, unaccepted Organization invitation."
    )
    parser.add_argument(
        "--organization-id",
        required=True,
        type=UUID,
        help="Existing Organization UUID",
    )
    parser.add_argument("--email", required=True, help="Existing invitation email")
    parser.add_argument(
        "--expires-hours",
        type=int,
        default=service.DEFAULT_INVITATION_TTL_HOURS,
        help="New invitation lifetime in hours (default: 168)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    with SessionLocal() as session:
        try:
            invitation = service.reissue_expired_invitation(
                session,
                organization_id=args.organization_id,
                email=args.email,
                expires_hours=args.expires_hours,
            )
        except ValidationError:
            parser.error("email must be valid and expires-hours must be greater than zero")
        except service.OrganizationInvitationOrganizationNotFoundError:
            parser.error("Organization does not exist")
        except service.OrganizationInvitationNotFoundError:
            parser.error("Organization invitation does not exist")
        except service.OrganizationInvitationActiveError:
            parser.error("Invitation is still active")
        except service.OrganizationInvitationAcceptedError:
            parser.error("Accepted invitations cannot be reissued")

    print("Invitation reissued.")
    print(f"Organization: {invitation.organization_id}")
    print(f"Email: {invitation.email}")
    print(f"Expires at: {invitation.expires_at.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
