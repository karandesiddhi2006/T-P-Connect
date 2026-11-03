import csv
import io
import re

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Student


REQUIRED_COLUMNS = [
    "roll_number",
    "full_name",
    "email",
    "branch",
    "graduation_year",
    "cgpa",
    "active_backlogs",
    "total_backlogs",
]

MAX_ROWS = 5000
MAX_FILE_BYTES = 5 * 1024 * 1024


def read_rows(filename: str, content: bytes):
    if len(content) > MAX_FILE_BYTES:
        raise ValueError("File exceeds the 5 MB limit.")

    extension = filename.lower().rsplit(".", 1)[-1]

    if extension == "csv":
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ValueError("CSV must use UTF-8 encoding.")

        reader = csv.DictReader(io.StringIO(text))

        if not reader.fieldnames:
            raise ValueError("CSV file has no header row.")

        headers = [
            header.strip().lower() if header else ""
            for header in reader.fieldnames
        ]

        if len(headers) != len(set(headers)):
            raise ValueError("CSV contains duplicate column names.")

        reader.fieldnames = headers
        rows = list(reader)

    elif extension == "xlsx":
        try:
            workbook = load_workbook(
                io.BytesIO(content),
                read_only=True,
                data_only=True,
            )
        except Exception:
            raise ValueError("The Excel file could not be opened.")

        try:
            sheet = workbook.active
            iterator = sheet.iter_rows(values_only=True)
            first_row = next(iterator, None)

            if not first_row:
                raise ValueError("Excel file has no header row.")

            headers = [
                str(value).strip().lower() if value is not None else ""
                for value in first_row
            ]

            if len(headers) != len(set(headers)):
                raise ValueError("Excel contains duplicate column names.")

            rows = [
                dict(zip(headers, values))
                for values in iterator
                if any(value is not None for value in values)
            ]
        finally:
            workbook.close()

    else:
        raise ValueError("Upload a .csv or .xlsx file.")

    missing = sorted(set(REQUIRED_COLUMNS) - set(headers))

    if missing:
        raise ValueError(
            "Missing required columns: " + ", ".join(missing)
        )

    if len(rows) > MAX_ROWS:
        raise ValueError(f"Maximum {MAX_ROWS} rows per upload.")

    return rows


def parse_student(row: dict):
    roll = str(row.get("roll_number") or "").strip().upper()
    name = " ".join(str(row.get("full_name") or "").split())
    email = str(row.get("email") or "").strip().lower()
    branch = " ".join(str(row.get("branch") or "").split())

    if not roll or len(roll) > 30:
        raise ValueError("Roll number is required (max 30 characters).")

    if not name or len(name) > 150:
        raise ValueError("Name is required (max 150 characters).")

    if len(email) > 255 or not re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+", email
    ):
        raise ValueError("Enter a valid email address.")

    if not branch or len(branch) > 100:
        raise ValueError("Branch is required (max 100 characters).")

    try:
        year = int(row["graduation_year"])
        cgpa = float(row["cgpa"])
        active = int(row["active_backlogs"])
        total = int(row["total_backlogs"])
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError(
            "Graduation year, CGPA and backlogs must be numeric."
        )

    if not 2020 <= year <= 2100:
        raise ValueError("Graduation year must be between 2020 and 2100.")

    if not 0 <= cgpa <= 10:
        raise ValueError("CGPA must be between 0 and 10.")

    if not 0 <= active <= total <= 100:
        raise ValueError(
            "Backlogs must satisfy 0 <= active <= total <= 100."
        )

    return {
        "roll_number": roll,
        "full_name": name,
        "email": email,
        "branch": branch,
        "graduation_year": year,
        "cgpa": cgpa,
        "active_backlogs": active,
        "total_backlogs": total,
    }


def import_students(db: Session, filename: str, content: bytes):
    rows = read_rows(filename, content)

    report = {
        "total": len(rows),
        "imported": 0,
        "rejected": [],
    }

    seen_rolls = set()
    seen_emails = set()

    try:
        for row_number, row in enumerate(rows, start=2):
            try:
                data = parse_student(row)

                if data["roll_number"] in seen_rolls:
                    raise ValueError(
                        "Duplicate roll number in uploaded file."
                    )

                if data["email"] in seen_emails:
                    raise ValueError(
                        "Duplicate email in uploaded file."
                    )

                # Check existing records in the database.
                existing = db.scalar(
                    select(Student.id).where(
                        (Student.roll_number == data["roll_number"])
                        | (Student.email == data["email"])
                    )
                )

                if existing:
                    raise ValueError(
                        "Roll number or email already exists in database."
                    )

                # A savepoint isolates an individual row's insert.
                # A rejected row won't undo previously accepted rows.
                with db.begin_nested():
                    db.add(Student(**data, is_active=True))
                    db.flush()

                seen_rolls.add(data["roll_number"])
                seen_emails.add(data["email"])
                report["imported"] += 1

            except ValueError as error:
                report["rejected"].append({
                    "row": row_number,
                    "reason": str(error),
                })

            except IntegrityError:
                report["rejected"].append({
                    "row": row_number,
                    "reason": (
                        "A duplicate record conflicts with database "
                        "constraints."
                    ),
                })

        # Commit all successfully inserted rows together.
        db.commit()

    except Exception:
        db.rollback()
        raise

    return report