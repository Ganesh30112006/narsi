"""Creates an administrator account, or resets an existing administrator's password. Administrators are the
only accounts that sign in, and there is no email-based reset — this script (run by someone with server access)
is how a forgotten password is recovered. Credentials come from the environment or a prompt, never from source.

    python scripts/create_admin.py --username admin --name "Admin User"
    (password read from BOOTSTRAP_ADMIN_PASSWORD, or prompted securely)

Resetting a password also signs the account out everywhere and clears any sign-in lockout.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.enums import PUBLIC_USER_ID, RoleName
from app.core.security import hash_password
from app.db.base import utcnow
from app.db.models import RefreshToken, User
from app.db.session import session_scope
from app.schemas.auth import check_password_strength, normalize_login_username
from app.services.auth_service import role_by_name


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--username", default=settings.bootstrap_admin_username)
    parser.add_argument("--name", default="Administrator")
    args = parser.parse_args()
    if not args.username:
        parser.error("--username is required (or set BOOTSTRAP_ADMIN_USERNAME)")
    try:
        username = normalize_login_username(args.username)
    except ValueError as exc:
        sys.exit(f"Username: {exc}")

    password = settings.bootstrap_admin_password.get_secret_value() if settings.bootstrap_admin_password else None
    if not password:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Repeat password: "):
            sys.exit("Passwords don't match.")
    try:
        check_password_strength(password)
    except ValueError as exc:
        sys.exit(str(exc))

    with session_scope() as session:
        role = role_by_name(session, RoleName.ADMIN)
        user = session.scalar(select(User).where(User.username == username))
        if user is not None and user.id == PUBLIC_USER_ID:
            sys.exit("That account is reserved.")
        if user is None:
            session.add(User(name=args.name, username=username, password_hash=hash_password(password), role_id=role.id))
            print(f"Created administrator {username}")
        else:
            user.role_id, user.password_hash, user.is_active = role.id, hash_password(password), True
            user.password_changed_at, user.failed_login_attempts, user.locked_until = utcnow(), 0, None
            session.execute(
                update(RefreshToken)
                .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=utcnow())
            )
            print(f"Reset the password for administrator {username} and signed it out everywhere")


if __name__ == "__main__":
    main()
