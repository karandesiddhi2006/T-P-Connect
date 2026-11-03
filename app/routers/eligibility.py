import csv
import html
import io

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PlacementDrive, Student, User
from app.security import SESSION_COOKIE, find_session

router = APIRouter()


def esc(value):
    return html.escape(str(value), quote=True)


def get_admin(request: Request, db: Session):
    session = find_session(db, request.cookies.get(SESSION_COOKIE))

    if session is None or session.user_id is None:
        return None, RedirectResponse("/login", status_code=303)

    user = db.get(User, session.user_id)

    if user is None or not user.is_active:
        return None, RedirectResponse("/login", status_code=303)

    if user.role != "admin":
        return None, HTMLResponse("Admin access required.", status_code=403)

    return session, None


def check_student(student: Student, drive: PlacementDrive) -> list[str]:
    reasons = []

    eligible_branches = [
        str(branch).strip().casefold()
        for branch in (drive.eligible_branches or [])
    ]
    if (student.branch or "").strip().casefold() not in eligible_branches:
        reasons.append("Branch is not eligible")

    if student.cgpa < drive.minimum_cgpa:
        reasons.append(
            f"CGPA {student.cgpa:.2f} is below the required {drive.minimum_cgpa:.2f}"
        )

    if student.graduation_year != drive.graduation_year:
        reasons.append(f"Graduation year must be {drive.graduation_year}")

    if student.active_backlogs > drive.maximum_active_backlogs:
        reasons.append(
            f"Active backlogs ({student.active_backlogs}) exceed the maximum "
            f"({drive.maximum_active_backlogs})"
        )

    if student.total_backlogs > drive.maximum_total_backlogs:
        reasons.append(
            f"Total backlogs ({student.total_backlogs}) exceed the maximum "
            f"({drive.maximum_total_backlogs})"
        )

    return reasons


def evaluate_students(students, drive):
    eligible = []
    ineligible = []
    for student in students:
        reasons = check_student(student, drive)
        if reasons:
            ineligible.append((student, reasons))
        else:
            eligible.append((student, []))
    return eligible, ineligible


def csv_response(rows, filename: str):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "Roll Number", "Full Name", "Email", "Branch", "Graduation Year",
        "CGPA", "Active Backlogs", "Total Backlogs", "Eligibility Status",
        "Reasons",
    ])
    for student, reasons in rows:
        # Prefix potentially formula-triggering user-controlled text to reduce
        # CSV formula injection risk when opened in spreadsheet applications.
        values = [
            student.roll_number, student.full_name, student.email, student.branch,
            student.graduation_year, f"{student.cgpa:.2f}",
            student.active_backlogs, student.total_backlogs,
            "Ineligible" if reasons else "Eligible",
            "; ".join(reasons) if reasons else "Meets all criteria",
        ]
        safe_values = []
        for value in values:
            text_value = "" if value is None else str(value)
            if text_value.startswith(("=", "+", "-", "@", "\t", "\r")):
                text_value = "'" + text_value
            safe_values.append(text_value)
        writer.writerow(safe_values)

    response = StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
    )
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/eligibility/export")
def export_eligibility(
    request: Request,
    drive_id: int,
    report: str = "all",
    db: Session = Depends(get_db),
):
    _, error_response = get_admin(request, db)
    if error_response:
        return error_response

    if report not in {"eligible", "ineligible", "all"}:
        return HTMLResponse("Invalid report type.", status_code=400)

    drive = db.get(PlacementDrive, drive_id)
    if drive is None:
        return HTMLResponse("Placement drive not found.", status_code=404)

    students = db.scalars(
        select(Student)
        .where(Student.is_active.is_(True))
        .order_by(Student.full_name.asc())
    ).all()
    eligible, ineligible = evaluate_students(students, drive)

    if report == "eligible":
        rows = eligible
        suffix = "eligible"
    elif report == "ineligible":
        rows = ineligible
        suffix = "ineligible"
    else:
        rows = eligible + ineligible
        suffix = "complete"

    safe_company = "".join(
        ch.lower() if ch.isalnum() else "_" for ch in drive.company_name
    ).strip("_")[:40] or "company"
    filename = f"{safe_company}_drive_{drive.id}_{suffix}.csv"
    return csv_response(rows, filename)


def render_page(content: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Eligibility Checker | T&amp;P Connect</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#f4f7fb;color:#18243a;font-family:Segoe UI,Arial,sans-serif}}
header{{background:#172747;color:white;padding:20px 5%}}
header a{{color:#dce7ff;text-decoration:none;margin-right:20px}}
main{{max-width:1200px;margin:30px auto;padding:0 20px}}
h1{{font-size:28px;margin-bottom:8px}}
.muted{{color:#68778d;font-size:14px}}
.panel{{background:white;border:1px solid #e1e8f1;border-radius:12px;padding:22px;margin:20px 0}}
label{{display:block;font-size:13px;font-weight:600;margin-bottom:8px}}
select{{width:100%;max-width:650px;padding:11px;border:1px solid #ccd6e5;border-radius:7px;margin:0 0 14px}}
button,.button{{display:inline-block;background:#2457d6;color:white;border:0;padding:11px 15px;border-radius:7px;cursor:pointer;font-weight:600;text-decoration:none;font-size:13px;margin:3px 5px 3px 0}}
.button.secondary{{background:#e8eefb;color:#23457c}}
.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}}
.stat{{background:#fff;border:1px solid #e1e8f1;border-radius:12px;padding:18px}}
.stat strong{{display:block;font-size:26px;margin-top:8px}}
.table-wrap{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;min-width:900px}}
th,td{{text-align:left;padding:12px;border-bottom:1px solid #e8edf4;font-size:13px;vertical-align:top}}
th{{background:#f6f8fc;color:#52627a}}
.ok{{color:#137547;font-weight:700}}
.no{{color:#b42336;font-weight:700}}
.notice{{background:#eaf2ff;padding:12px;border-radius:8px;color:#23457c;margin:14px 0}}
@media(max-width:760px){{.grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<header>
<strong style="margin-right:25px">T&amp;P Connect</strong>
<a href="/dashboard">Dashboard</a>
<a href="/students">Student Records</a>
<a href="/drives">Placement Drives</a>
<a href="/eligibility">Eligibility Checker</a>
</header>
<main>{content}</main>
</body>
</html>"""


@router.get("/eligibility", response_class=HTMLResponse)
def eligibility_checker(
    request: Request,
    drive_id: int | None = None,
    db: Session = Depends(get_db),
):
    _, error_response = get_admin(request, db)
    if error_response:
        return error_response

    drives = db.scalars(
        select(PlacementDrive).order_by(PlacementDrive.created_at.desc())
    ).all()

    if not drives:
        return HTMLResponse(render_page("""
<h1>Eligibility Checker</h1>
<p class="muted">Compare student records with placement-drive requirements.</p>
<div class="panel">
<p>No placement drives have been created yet.</p>
<a class="button" href="/drives">Create a placement drive</a>
</div>
"""))

    selected_drive = db.get(PlacementDrive, drive_id) if drive_id is not None else drives[0]

    if drive_id is not None and selected_drive is None:
        return HTMLResponse(
            render_page('<div class="panel"><h1>Drive not found</h1><p>The selected placement drive does not exist.</p><a href="/eligibility">Go back</a></div>'),
            status_code=404,
        )

    options = "".join(
        f'<option value="{drive.id}" {"selected" if drive.id == selected_drive.id else ""}>'
        f'{esc(drive.company_name)} — {esc(drive.job_role)} '
        f'(Class of {drive.graduation_year}, {esc(drive.status.title())})</option>'
        for drive in drives
    )

    students = db.scalars(
        select(Student)
        .where(Student.is_active.is_(True))
        .order_by(Student.full_name.asc())
    ).all()
    eligible, ineligible = evaluate_students(students, selected_drive)

    def table(rows, empty_message):
        if not rows:
            return f'<p class="muted">{empty_message}</p>'
        rendered_rows = []
        for student, reasons in rows:
            details = (
                "<br>".join(esc(reason) for reason in reasons)
                if reasons else '<span class="ok">Meets all criteria</span>'
            )
            rendered_rows.append(f"""
<tr>
<td>{esc(student.roll_number)}</td>
<td>{esc(student.full_name)}</td>
<td>{esc(student.branch)}</td>
<td>{student.graduation_year}</td>
<td>{student.cgpa:.2f}</td>
<td>{student.active_backlogs}</td>
<td>{student.total_backlogs}</td>
<td>{details}</td>
</tr>""")
        return f"""
<div class="table-wrap"><table>
<thead><tr>
<th>Roll No.</th><th>Student</th><th>Branch</th><th>Graduation Year</th>
<th>CGPA</th><th>Active Backlogs</th><th>Total Backlogs</th><th>Eligibility details</th>
</tr></thead><tbody>{''.join(rendered_rows)}</tbody></table></div>"""

    criteria = ", ".join(esc(branch) for branch in (selected_drive.eligible_branches or []))
    package = (
        f"{selected_drive.package_lpa:.2f} LPA"
        if selected_drive.package_lpa is not None
        else "Not specified"
    )
    export_buttons = f"""
<a class="button" href="/eligibility/export?drive_id={selected_drive.id}&amp;report=eligible">Download Eligible CSV</a>
<a class="button" href="/eligibility/export?drive_id={selected_drive.id}&amp;report=ineligible">Download Ineligible CSV</a>
<a class="button secondary" href="/eligibility/export?drive_id={selected_drive.id}&amp;report=all">Download Complete CSV</a>
"""

    content = f"""
<h1>Eligibility Checker</h1>
<p class="muted">Check active student records against the saved criteria for a placement drive. This tool does not modify records.</p>
<div class="panel">
<form method="get" action="/eligibility">
<label for="drive_id">Select placement drive</label>
<select id="drive_id" name="drive_id">{options}</select>
<button type="submit">Check Eligibility</button>
</form>
<div class="notice"><strong>Drive criteria:</strong>
Minimum CGPA: {selected_drive.minimum_cgpa:.2f} ·
Graduation year: {selected_drive.graduation_year} ·
Eligible branches: {criteria or "None specified"} ·
Maximum active backlogs: {selected_drive.maximum_active_backlogs} ·
Maximum total backlogs: {selected_drive.maximum_total_backlogs} ·
Package: {esc(package)}
</div>
<p class="muted">Drive status: {esc(selected_drive.status.title())}. The checker can review saved drives regardless of status; it does not open applications.</p>
<h3>Export results</h3>
<p class="muted">Download the current drive's results as CSV files that open in Excel.</p>
{export_buttons}
</div>
<div class="grid">
<div class="stat">Active students checked<strong>{len(students)}</strong></div>
<div class="stat">Eligible students<strong>{len(eligible)}</strong></div>
<div class="stat">Ineligible students<strong>{len(ineligible)}</strong></div>
</div>
<div class="panel"><h2>Eligible Students</h2>
{table(eligible, "No active students currently meet every criterion for this drive.")}</div>
<div class="panel"><h2>Ineligible Students</h2>
{table(ineligible, "All checked students meet the selected drive's criteria.")}</div>
"""
    return HTMLResponse(render_page(content))
