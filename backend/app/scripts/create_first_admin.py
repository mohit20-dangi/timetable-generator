"""Bootstrap the very first admin account, bypassing the invite requirement.

Run once, from backend/, with the venv active:
    python -m app.scripts.create_first_admin

Every admin after this one must be created via POST /api/auth/register with
an invite token minted by an existing admin (POST /api/auth/invites).
"""
import getpass
import sys
from datetime import datetime, timezone
from app.db import get_database
from app.auth.security import hash_password


def main():
    db = get_database()

    if db.admins.count_documents({}) > 0:
        print("An admin account already exists. Use the invite flow (POST /api/auth/invites) instead.")
        sys.exit(1)

    username = input("Choose an admin username: ").strip()
    if not username:
        print("Username cannot be empty.")
        sys.exit(1)

    password = getpass.getpass("Choose a password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords did not match.")
        sys.exit(1)
    if len(password) < 8:
        print("Password should be at least 8 characters.")
        sys.exit(1)

    db.admins.insert_one({
        "_id": username,
        "hashed_password": hash_password(password),
        "created_at": datetime.now(timezone.utc),
    })
    print(f"Admin '{username}' created. You can now log in via POST /api/auth/login.")


if __name__ == "__main__":
    main()
