import html
import hmac
import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Student, User
from app.security import SESSION_COOKIE, find_session
from fastapi import File, UploadFile
from app.services.student_import import import_students
router = APIRouter()


def escape(value):
    return html.escape(str(value), quote=True)


def get_admin(request: Request, db: Session):
    session = find_session(
        db, request.cookies.get(SESSION_COOKIE)
    )

    if session is None or session.user_id is None:
        return None, RedirectResponse("/login", status_code=303)

    user = db.get(User, session.user_id)

    if user is None or not user.is_active:
        return None, RedirectResponse("/login", status_code=303)

    if user.role != "admin":
        return None, HTMLResponse(
            "Administrator access required.", status_code=403
        )

    return session, None


def page(title: str, content: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} | T&amp;P Connect</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#f4f7fb;color:#18243a;
font-family:Segoe UI,Arial,sans-serif}}
header{{background:#172747;color:white;padding:20px 5%}}
header a{{color:#dce7ff;text-decoration:none;margin-right:20px}}
main{{max-width:1200px;margin:30px auto;padding:0 20px}}
h1{{font-size:28px;margin-bottom:8px}}
.muted{{color:#68778d;font-size:14px}}
.panel{{background:white;border:1px solid #e1e8f1;
border-radius:12px;padding:22px;margin:20px 0}}
.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));
gap:14px}}
label{{display:block;font-size:13px;font-weight:600}}
input{{width:100%;padding:11px;margin:7px 0 14px;
border:1px solid #ccd6e5;border-radius:7px;font-size:14px}}
button,.button{{display:inline-block;background:#2457d6;color:white;
border:0;padding:11px 15px;border-radius:7px;cursor:pointer;
font-weight:600;text-decoration:none;font-size:13px}}
.secondary{{background:#e9eef8;color:#233a62}}
.danger{{background:#a82b3b}}
table{{width:100%;border-collapse:collapse;min-width:900px}}
th,td{{text-align:left;padding:12px;border-bottom:1px solid #e8edf4;
font-size:13px;vertical-align:middle}}
th{{background:#f6f8fc;color:#52627a}}
.table-wrap{{overflow-x:auto}}
.notice{{background:#eaf2ff;padding:12px;border-radius:8px;
margin:15px 0;color:#23457c;font-size:14px}}
.error{{background:#fff0f0;color:#9c2531;padding:12px;
border-radius:8px;margin:15px 0}}
.inline{{display:inline}}
.inline button{{padding:8px 10px}}
.toolbar{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}}
.toolbar input{{max-width:400px;margin:0}}
@media(max-width:760px){{.grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<header>
  <strong style="margin-right:25px">T&amp;P Connect</strong>
  <a href="/dashboard">Dashboard</a>
  <a href="/students">Student Records</a>
</header>
<main>
{content}
</main>
</body>
</html>"""


def student_form(csrf_token: str, error: str = "") -> str:
    error_html = (
        f'<div class="error">{escape(error)}</div>' if error else ""
    )

    return f"""
<h2>Add a student</h2>
<p class="muted">Enter the student's academic and placement details.</p>
{error_html}
<form method="post" action="/students">
<input type="hidden" name="csrf_token"
 value="{escape(csrf_token)}">
<div class="grid">
  <div><label>Roll number
  <input name="roll_number" maxlength="30" required></label></div>
  <div><label>Full name
  <input name="full_name" maxlength="150" required></label></div>
  <div><label>Email
  <input name="email" type="email" maxlength="255" required></label></div>
  <div><label>Branch
  <input name="branch" maxlength="100" required
  placeholder="e.g. CSE (AI &amp; ML)"></label></div>
  <div><label>Graduation year
  <input name="graduation_year" type="number" min="2020"
  max="2100" required></label></div>
  <div><label>CGPA (0–10)
  <input name="cgpa" type="number" min="0" max="10"
  step="0.01" required></label></div>
  <div><label>Active backlogs
  <input name="active_backlogs" type="number" min="0"
  max="100" value="0" required></label></div>
  <div><label>Total backlogs
  <input name="total_backlogs" type="number" min="0"
  max="100" value="0" required></label></div>
</div>
<button type="submit">Save student</button>
<a class="button secondary" href="/students">Cancel</a>
</form>"""


@router.get("/students", response_class=HTMLResponse)
def list_students(
    request: Request,
    search: str = "",
    db: Session = Depends(get_db),
):
    current, error_response = get_admin(request, db)

    if error_response:
        return error_response

    search = search.strip()[:100]

    statement = select(Student).where(Student.is_active.is_(True))

    if search:
        pattern = f"%{search}%"
        statement = statement.where(
            or_(
                Student.full_name.ilike(pattern),
                Student.roll_number.ilike(pattern),
                Student.email.ilike(pattern),
            )
        )

    statement = statement.order_by(Student.full_name).limit(500)
    students = db.scalars(statement).all()

    rows = ""

    for student in students:
        rows += f"""
<tr>
<td>{escape(student.roll_number)}</td>
<td>{escape(student.full_name)}</td>
<td>{escape(student.email)}</td>
<td>{escape(student.branch)}</td>
<td>{student.graduation_year}</td>
<td>{student.cgpa:.2f}</td>
<td>{student.active_backlogs} / {student.total_backlogs}</td>
<td>
<form class="inline" method="post"
 action="/students/{student.id}/deactivate"
 onsubmit="return confirm('Deactivate this student record?')">
<input type="hidden" name="csrf_token"
 value="{escape(current.csrf_token)}">
<button class="danger" type="submit">Deactivate</button>
</form>
</td>
</tr>"""

    if not rows:
        rows = """
<tr><td colspan="8">
No active student records found. Add a student to get started.
</td></tr>"""

    safe_search = escape(search)

    content = f"""
<h1>Student Management</h1>
<p class="muted">Manage student academic profiles for placement drives.</p>
<section class="panel">
{student_form(current.csrf_token)}
</section>

<section class="panel">
<h2>Import students in bulk</h2>
<p class="muted">
Upload a CSV or Excel (.xlsx) file using the required column names.
Maximum file size: 5 MB.
</p>
<form method="post" action="/students/import"
 enctype="multipart/form-data">
<input type="hidden" name="csrf_token"
 value="{escape(current.csrf_token)}">
<label for="student-file">Student spreadsheet</label>
<input id="student-file" type="file" name="file"
 accept=".csv,.xlsx" required>
<button type="submit">Upload and import</button>
</form>
</section>
<section class="panel">
<h2>Student records ({len(students)})</h2>
<form class="toolbar" method="get" action="/students">
<input name="search" value="{safe_search}"
 placeholder="Search name, roll number or email">
<button type="submit">Search</button>
<a class="button secondary" href="/students">Clear</a>
</form>
<p class="muted">Showing up to 500 matching active records.</p>
<div class="table-wrap">
<table>
<thead><tr>
<th>Roll number</th><th>Name</th><th>Email</th><th>Branch</th>
<th>Graduation year</th><th>CGPA</th><th>Backlogs (active / total)</th>
<th>Action</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>
</div>
</section>"""

    return HTMLResponse(page("Student Management", content))


@router.post("/students", response_class=HTMLResponse)
def create_student(
    request: Request,
    csrf_token: str = Form(..., max_length=100),
    roll_number: str = Form(..., max_length=30),
    full_name: str = Form(..., max_length=150),
    email: str = Form(..., max_length=255),
    branch: str = Form(..., max_length=100),
    graduation_year: int = Form(..., ge=2020, le=2100),
    cgpa: float = Form(..., ge=0, le=10),
    active_backlogs: int = Form(..., ge=0, le=100),
    total_backlogs: int = Form(..., ge=0, le=100),
    db: Session = Depends(get_db),
):
    current, error_response = get_admin(request, db)

    if error_response:
        return error_response

    if not hmac.compare_digest(current.csrf_token, csrf_token):
        return HTMLResponse(
            "Form expired. Reload the student page and try again.",
            status_code=403,
        )

    roll_number = roll_number.strip().upper()
    full_name = " ".join(full_name.split())
    email = email.strip().lower()
    branch = " ".join(branch.split())

    if not roll_number or not full_name or not branch:
        return HTMLResponse(
            page("Student Management", student_form(
                current.csrf_token, "All text fields are required."
            )),
            status_code=400,
        )

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return HTMLResponse(
            page("Student Management", student_form(
                current.csrf_token, "Enter a valid email address."
            )),
            status_code=400,
        )

    if active_backlogs > total_backlogs:
        return HTMLResponse(
            page("Student Management", student_form(
                current.csrf_token,
                "Active backlogs cannot exceed total backlogs.",
            )),
            status_code=400,
        )

    duplicate = db.scalar(
        select(Student.id).where(
            or_(
                Student.roll_number == roll_number,
                Student.email == email,
            )
        )
    )

    if duplicate:
        return HTMLResponse(
            page("Student Management", student_form(
                current.csrf_token,
                "A student with this roll number or email already exists.",
            )),
            status_code=409,
        )

    student = Student(
        roll_number=roll_number,
        full_name=full_name,
        email=email,
        branch=branch,
        graduation_year=graduation_year,
        cgpa=cgpa,
        active_backlogs=active_backlogs,
        total_backlogs=total_backlogs,
        is_active=True,
    )

    db.add(student)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return HTMLResponse(
            page("Student Management", student_form(
                current.csrf_token,
                "The roll number or email already exists. Please check and retry.",
            )),
            status_code=409,
        )

    return RedirectResponse("/students", status_code=303)


@router.post("/students/{student_id}/deactivate")
def deactivate_student(
    student_id: int,
    request: Request,
    csrf_token: str = Form(..., max_length=100),
    db: Session = Depends(get_db),
):
    current, error_response = get_admin(request, db)

    if error_response:
        return error_response

    if not hmac.compare_digest(current.csrf_token, csrf_token):
        return HTMLResponse(
            "Form expired. Reload the page and try again.",
            status_code=403,
        )

    student = db.get(Student, student_id)

    if student is None:
        return HTMLResponse("Student not found.", status_code=404)

    student.is_active = False
    db.commit()

    return RedirectResponse("/students", status_code=303)

@router.post("/students/import", response_class=HTMLResponse)
async def upload_students(
    request: Request,
    file: UploadFile = File(...),
    csrf_token: str = Form(..., max_length=100),
    db: Session = Depends(get_db),
):
    current, error_response = get_admin(request, db)

    if error_response:
        await file.close()
        return error_response

    if not hmac.compare_digest(current.csrf_token, csrf_token):
        await file.close()
        return HTMLResponse(
            "Form expired. Reload the page and try again.",
            status_code=403,
        )

    try:
        content = await file.read(5 * 1024 * 1024 + 1)

        report = import_students(
            db,
            file.filename or "",
            content,
        )
    except ValueError as error:
        return HTMLResponse(
            page(
                "Student Import",
                f'<section class="panel"><h1>Import failed</h1>'
                f'<p>{escape(error)}</p>'
                f'<a class="button" href="/students">Back to students</a>'
                f'</section>',
            ),
            status_code=400,
        )
    finally:
        await file.close()

    rejected_rows = "".join(
        "<tr>"
        f"<td>{item['row']}</td>"
        f"<td>{escape(item['reason'])}</td>"
        "</tr>"
        for item in report["rejected"]
    )

    if not rejected_rows:
        rejected_rows = (
            '<tr><td colspan="2">No rejected rows.</td></tr>'
        )

    content_html = f"""
    <h1>Import Results</h1>
    <section class="panel">
      <p>Total rows: <strong>{report["total"]}</strong></p>
      <p>Imported successfully:
         <strong>{report["imported"]}</strong></p>
      <p>Rejected rows:
         <strong>{len(report["rejected"])}</strong></p>
    </section>
    <section class="panel">
      <h2>Rejected row details</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Row number</th><th>Reason</th></tr></thead>
          <tbody>{rejected_rows}</tbody>
        </table>
      </div>
    </section>
    <a class="button" href="/students">Back to Student Management</a>
    """

    return HTMLResponse(page("Import Results", content_html))

