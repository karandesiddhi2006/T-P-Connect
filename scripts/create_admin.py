import getpass

from sqlalchemy import select

from app.database import SessionLocal
from app.models import User
from app.security import hash_password


def main():
    email = input("Administrator email: ").strip().lower()

    if (
        not email
        or len(email) > 255
        or "@" not in email
        or any(ch.isspace() for ch in email)
    ):
        raise SystemExit("Enter a valid email address.")

    password = getpass.getpass("New password (hidden): ")
    confirmation = getpass.getpass("Confirm password: ")

    if password != confirmation:
        raise SystemExit("Passwords do not match.")

    try:
        password_hash = hash_password(password)
    except ValueError as error:
        raise SystemExit(str(error))

    with SessionLocal() as db:
        # Allow only the first administrator to be created.
        if db.scalar(
            select(User.id).where(User.role == "admin")
        ):
            raise SystemExit(
                "An administrator already exists. "
                "Bootstrap is disabled."
            )

        # Prevent duplicate email addresses.
        if db.scalar(
            select(User.id).where(User.email == email)
        ):
            raise SystemExit(
                "That email already has an account."
            )

        db.add(
            User(
                email=email,
                password_hash=password_hash,
                role="admin",
                is_active=True,
            )
        )

        try:
            db.commit()
        except Exception:
            db.rollback()
            raise SystemExit(
                "Account creation failed. Check whether the email "
                "already exists and retry."
            )

    print("Administrator created successfully.")


if __name__ == "__main__":
    main()
