import argparse
from collections.abc import Sequence

from pydantic import ValidationError

from app.core.platform_admin import service
from app.database import SessionLocal


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Grant global Auron Platform Admin access to an existing User."
    )
    parser.add_argument("--email", required=True, help="Existing Auron User email")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    with SessionLocal() as session:
        try:
            platform_admin, created = service.grant_platform_admin(
                session, args.email
            )
        except ValidationError:
            parser.error("email must be a valid email address")
        except service.PlatformAdminUserNotFoundError:
            parser.error("no existing Auron User has that email address")

    outcome = "granted" if created else "already granted"
    print(f"Platform Admin access {outcome} for User {platform_admin.user_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
