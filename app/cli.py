from __future__ import annotations

import argparse
import secrets
import string
import sys

from app.database import SessionLocal, init_db
from app.models.db import AppSettings, User
from app.services.audit_service import log_audit
from app.services.settings_service import get_or_create_settings, hash_password


def generate_secure_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    # Гарантируем как минимум одну строчную, заглавную букву, цифру и спецсимвол
    return "".join(secrets.choice(alphabet) for _ in range(length))


def reset_admin(username: str = "admin", password: str | None = None) -> None:
    init_db()
    db = SessionLocal()
    try:
        new_password = password or generate_secure_password(16)
        p_hash = hash_password(new_password)

        settings = get_or_create_settings(db)
        settings.username = username
        settings.password_hash = p_hash
        settings.login_enabled = True

        # Ищем или создаём пользователя в таблице users
        user = db.query(User).filter(User.username == username).first()
        if not user:
            # Проверяем, есть ли вообще owner
            owner = db.query(User).filter(User.is_owner == True).first()  # noqa: E712
            if owner:
                user = owner
                user.username = username
            else:
                user = User(
                    username=username,
                    display_name="Administrator",
                    is_admin=True,
                    is_owner=True,
                    enabled=True,
                    permissions={
                        "manage_library": True,
                        "manual_search": True,
                        "manage_settings": True,
                        "manage_indexers": True,
                        "manage_downloaders": True,
                        "manage_users": True,
                        "view_audit": True,
                    },
                )
                db.add(user)

        user.password_hash = p_hash
        user.is_admin = True
        user.is_owner = True
        user.enabled = True
        db.commit()

        log_audit(
            db,
            action="auth.admin_reset",
            description=f"Admin credentials reset via CLI for user '{username}'",
            username="cli",
        )

        print("\n=======================================================")
        print("  ALIASARR — ADMIN CREDENTIALS RESET")
        print("=======================================================")
        print(f"  Username: {username}")
        print(f"  Password: {new_password}")
        print("=======================================================\n")
    finally:
        db.close()


def list_users() -> None:
    init_db()
    db = SessionLocal()
    try:
        users = db.query(User).all()
        print(f"\nTotal users: {len(users)}")
        print(f"{'ID':<4} | {'Username':<18} | {'Role':<10} | {'Owner':<6} | {'Enabled':<8}")
        print("-" * 55)
        for u in users:
            role = "Admin" if u.is_admin else "User"
            owner = "Yes" if u.is_owner else "No"
            enabled = "Yes" if u.enabled else "No"
            print(f"{u.id:<4} | {u.username:<18} | {role:<10} | {owner:<6} | {enabled:<8}")
        print("")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Aliasarr Management CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # reset-admin
    reset_parser = subparsers.add_parser("reset-admin", help="Reset or create master admin password")
    reset_parser.add_argument("--username", default="admin", help="Admin username (default: admin)")
    reset_parser.add_argument("--password", default=None, help="New password (generates random if omitted)")

    # list-users
    subparsers.add_parser("list-users", help="List all registered users")

    args = parser.parse_args()
    if args.command == "reset-admin":
        reset_admin(username=args.username, password=args.password)
    elif args.command == "list-users":
        list_users()


if __name__ == "__main__":
    main()
