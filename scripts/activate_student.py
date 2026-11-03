
from getpass import getpass

from app.database import SessionLocal
from app.models import Student, User
from app.security import hash_password

EMAIL = input("Student email: ").strip().lower()

db = SessionLocal()

try:
    student = db.query(Student).filter(
        Student.email == EMAIL
    ).first()

    if student is None:
        print("Student record not found.")
        raise SystemExit

    if not student.is_active:
        student.is_active = True

    user = db.query(User).filter(
        User.email == EMAIL
    ).first()

    if user and user.role != "student":
        print("This email belongs to a non-student account.")
        raise SystemExit

    password = getpass("Create student password (12-128 characters): ")
    confirm = getpass("Confirm password: ")

    if password != confirm:
        print("Passwords do not match.")
        raise SystemExit

    if len(password) < 12 or len(password) > 128:
        print("Password must contain 12-128 characters.")
        raise SystemExit

    if user is None:
        user = User(
            email=EMAIL,
            password_hash=hash_password(password),
            role="student",
            is_active=True,
        )
        db.add(user)
    else:
        user.password_hash = hash_password(password)
        user.is_active = True

    db.commit()

    print("\nSUCCESS!")
    print("Student record: Active")
    print("Student login: Created/updated")
    print("Role: student")
    print("Email:", EMAIL)

except SystemExit:
    db.rollback()
except Exception:
    db.rollback()
    raise
finally:
    db.close()
