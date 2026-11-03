
import html
import hmac
import math
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Application,
    ApplicationRoundResult,
    PlacementDrive,
    RecruitmentRound,
    Student,
    User,
    Notification,
)
from app.routers.eligibility import evaluate_students, check_student
from app.security import SESSION_COOKIE, find_session

router = APIRouter()


def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def get_admin(request: Request, db: Session):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None, RedirectResponse("/login", status_code=303)

    session = find_session(db, token)
    if not session:
        return None, RedirectResponse("/login", status_code=303)

    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None, RedirectResponse("/login", status_code=303)

    if user.role != "admin":
        return None, HTMLResponse("Admin access required.", status_code=403)

    return session, None


def get_logged_in_user(request: Request, db: Session):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None, RedirectResponse("/", status_code=303)

    session = find_session(db, token)
    if session is None:
        return None, RedirectResponse("/", status_code=303)

    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None, RedirectResponse("/", status_code=303)

    return (session, user), None


def _extract_student(item):
    """Extract a Student from an eligibility result."""
    if isinstance(item, Student):
        return item

    if isinstance(item, (tuple, list)):
        for part in item:
            if isinstance(part, Student):
                return part
            if isinstance(part, (tuple, list)):
                for nested_part in part:
                    if isinstance(nested_part, Student):
                        return nested_part

    return None


def valid_csrf(session, token):
    return bool(
        token
        and session.csrf_token
        and hmac.compare_digest(session.csrf_token, token)
    )


def render_page(title: str, content: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} | T&amp;P Connect</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;padding:24px;background:#f4f6fa;color:#202b3c;
font-family:Arial,sans-serif}}
main{{max-width:1150px;margin:auto}}
.panel{{background:white;padding:22px;margin:18px 0;
border-radius:12px;box-shadow:0 2px 10px #0000000a}}
input,select,textarea{{box-sizing:border-box;padding:9px;margin:5px 0 12px;
border:1px solid #ccd3df;border-radius:6px;max-width:100%}}
input[type=text],input[type=datetime-local],input[type=number],
textarea{{width:100%}}
label{{display:block;font-weight:600;font-size:13px}}
button,.button{{background:#234bc7;color:white;border:0;border-radius:6px;
padding:10px 13px;cursor:pointer;text-decoration:none;display:inline-block}}
.secondary{{background:#475569}}
table{{width:100%;border-collapse:collapse}}
th,td{{text-align:left;padding:10px;border-bottom:1px solid #e5e9f0;
vertical-align:top}}
th{{background:#f8fafc}}
.table-wrap{{overflow-x:auto}}
.muted{{color:#64748b}}
.notice{{background:#eff6ff;padding:12px;border-radius:8px;margin:15px 0}}
.success{{background:#ecfdf5;border-left:4px solid #16a34a;
padding:12px;border-radius:6px;margin:15px 0}}
form{{margin:0}}
.inline-form{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}
.inline-form select,.inline-form input{{margin:0}}
@media(max-width:650px){{body{{padding:12px}}.panel{{padding:14px}}}}
</style>
</head>
<body>
<main>
<p>
<a href="/dashboard">Dashboard</a> ·
<a href="/students">Student Records</a> ·
<a href="/drives">Placement Drives</a> ·
<a href="/eligibility">Eligibility Checker</a> ·
<a href="/applications">Applications</a>
</p>
{content}
</main>
</body>
</html>"""


@router.get("/applications", response_class=HTMLResponse)
def list_applications(
    request: Request,
    db: Session = Depends(get_db),
):
    session, error = get_admin(request, db)
    if error:
        return error

    drives = db.scalars(
        select(PlacementDrive)
        .where(PlacementDrive.status != "archived")
        .order_by(PlacementDrive.created_at.desc())
    ).all()

    rows = ""

    for drive in drives:
        count = db.scalar(
            select(func.count())
            .select_from(Application)
            .where(Application.drive_id == drive.id)
        ) or 0

        round_count = db.scalar(
            select(func.count())
            .select_from(RecruitmentRound)
            .where(RecruitmentRound.drive_id == drive.id)
        ) or 0

        rows += f"""
        <tr>
          <td>{esc(drive.company_name)}</td>
          <td>{esc(drive.job_role)}</td>
          <td>{esc(drive.status.title())}</td>
          <td>{count}</td>
          <td>{round_count}</td>
          <td>
            <a class="button" href="/applications/{drive.id}">Manage</a>
          </td>
        </tr>
        """

    if not rows:
        rows = """
        <tr>
          <td colspan="6">No placement drives found. Create a drive first.</td>
        </tr>
        """

    content = f"""
    <h1>Applications &amp; Recruitment Rounds</h1>
    <p class="muted">
      Manage applicants and record recruitment progress company by company.
    </p>
    <section class="panel">
      <h2>Placement drives</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Company</th><th>Role</th><th>Drive status</th>
              <th>Applicants</th><th>Rounds</th><th>Action</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </section>
    """
    return HTMLResponse(render_page("Applications", content))


@router.get("/applications/{drive_id}", response_class=HTMLResponse)
def manage_drive_applications(
    drive_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    session, error = get_admin(request, db)
    if error:
        return error

    drive = db.get(PlacementDrive, drive_id)
    if drive is None:
        return HTMLResponse("Placement drive not found.", status_code=404)

    safe_csrf = esc(session.csrf_token)

    # Read import result from the redirect query parameters.
    added_param = request.query_params.get("added")
    skipped_param = request.query_params.get("skipped")
    import_result = ""

    if added_param is not None and skipped_param is not None:
        try:
            added_count = int(added_param)
            skipped_count = int(skipped_param)

            if added_count < 0 or skipped_count < 0:
                raise ValueError

            import_result = f"""
            <div class="success">
              <strong>Eligible student import completed!</strong><br>
              Students added: {added_count}<br>
              Existing applications skipped: {skipped_count}
            </div>
            """
        except ValueError:
            import_result = ""

    rounds = db.scalars(
        select(RecruitmentRound)
        .where(RecruitmentRound.drive_id == drive_id)
        .order_by(RecruitmentRound.round_number)
    ).all()

    applications = db.scalars(
        select(Application)
        .where(Application.drive_id == drive_id)
        .order_by(Application.applied_at.desc())
    ).all()

    round_rows = ""

    for rnd in rounds:
        scheduled = (
            rnd.scheduled_at.strftime("%d %b %Y, %I:%M %p")
            if rnd.scheduled_at else "Not scheduled"
        )

        round_rows += f"""
        <tr>
          <td>{rnd.round_number}</td>
          <td>{esc(rnd.name)}</td>
          <td>{esc(scheduled)}</td>
          <td>{esc(rnd.status.title())}</td>
          <td>{esc(rnd.description or "")}</td>
        </tr>
        """

    if not round_rows:
        round_rows = """
        <tr><td colspan="5">No rounds created yet.</td></tr>
        """

    applicant_rows = ""

    for application in applications:
        student = db.get(Student, application.student_id)
        if student is None:
            continue

        status_options = ""

        for value in (
            "applied", "shortlisted", "rejected", "selected", "withdrawn"
        ):
            selected = (
                "selected" if application.status == value else ""
            )
            status_options += (
                f'<option value="{value}" {selected}>'
                f'{value.title()}</option>'
            )

        applicant_rows += f"""
        <tr>
          <td>{esc(student.roll_number)}</td>
          <td>{esc(student.full_name)}</td>
          <td>{esc(student.email)}</td>
          <td>
            <form method="post"
                  action="/applications/{drive_id}/applicant/{application.id}/status"
                  class="inline-form">
              <input type="hidden" name="csrf_token" value="{safe_csrf}">
              <select name="status">{status_options}</select>
              <button type="submit">Save</button>
            </form>
          </td>
        </tr>
        """

    if not applicant_rows:
        applicant_rows = """
        <tr><td colspan="4">No applicants found yet.</td></tr>
        """

    results_html = ""

    if rounds and applications:
        result_rows = ""

        for application in applications:
            student = db.get(Student, application.student_id)
            if student is None:
                continue

            for rnd in rounds:
                result = db.scalar(
                    select(ApplicationRoundResult).where(
                        ApplicationRoundResult.application_id == application.id,
                        ApplicationRoundResult.round_id == rnd.id,
                    )
                )

                current_result = result.result if result else "pending"
                current_score = (
                    str(result.score)
                    if result and result.score is not None else ""
                )
                current_remarks = result.remarks if result else ""

                result_options = ""

                for value in ("pending", "passed", "failed", "absent"):
                    selected = (
                        "selected" if current_result == value else ""
                    )
                    result_options += (
                        f'<option value="{value}" {selected}>'
                        f'{value.title()}</option>'
                    )

                result_rows += f"""
                <tr>
                  <td>
                    {esc(student.roll_number)} — {esc(student.full_name)}
                  </td>
                  <td>{esc(rnd.name)}</td>
                  <td>
                    <form method="post"
                          action="/applications/{drive_id}/result"
                          class="inline-form">
                      <input type="hidden" name="csrf_token" value="{safe_csrf}">
                      <input type="hidden" name="application_id"
                             value="{application.id}">
                      <input type="hidden" name="round_id" value="{rnd.id}">
                      <select name="result">{result_options}</select>
                      <input type="number" name="score" min="0"
                             step="0.01" placeholder="Score (optional)"
                             value="{esc(current_score)}">
                      <input type="text" name="remarks" maxlength="1000"
                             placeholder="Remarks (optional)"
                             value="{esc(current_remarks)}">
                      <button type="submit">Save result</button>
                    </form>
                  </td>
                </tr>
                """

        results_html = f"""
        <section class="panel">
          <h2>Round results</h2>
          <p class="muted">
            Save a result for each applicant in each recruitment round.
          </p>
          <div class="table-wrap">
            <table>
              <thead>
                <tr><th>Student</th><th>Round</th><th>Result</th></tr>
              </thead>
              <tbody>{result_rows}</tbody>
            </table>
          </div>
        </section>
        """

    content = f"""
    <h1>{esc(drive.company_name)} — Recruitment Management</h1>
    <p class="muted">
      Role: {esc(drive.job_role)} ·
      Drive status: {esc(drive.status.title())}
    </p>

    {import_result}

    <section class="panel">
      <h2>Add Eligible Students</h2>
      <p class="muted">
        Check active student records against this drive's saved eligibility
        criteria. Existing applicants will not be added again.
      </p>
      <form method="post"
            action="/applications/{drive_id}/add-eligible"
            onsubmit="return confirm('Add all eligible students to this drive?');">
        <input type="hidden" name="csrf_token" value="{safe_csrf}">
        <button type="submit">Add Eligible Students</button>
      </form>
    </section>

    <section class="panel">
      <h2>Create a recruitment round</h2>
      <form method="post" action="/applications/{drive_id}/rounds">
        <input type="hidden" name="csrf_token" value="{safe_csrf}">

        <label for="name">Round name *</label>
        <input id="name" name="name" type="text" maxlength="100"
               placeholder="Aptitude Test / Technical Interview / HR Interview"
               required>

        <label for="scheduled_at">
          Scheduled date and time (optional)
        </label>
        <input id="scheduled_at" name="scheduled_at"
               type="datetime-local">

        <label for="description">Description (optional)</label>
        <textarea id="description" name="description"
                  maxlength="2000" rows="3"></textarea>

        <button type="submit">Create Round</button>
      </form>
    </section>

    <section class="panel">
      <h2>Recruitment rounds</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>No.</th><th>Round</th><th>Schedule</th>
              <th>Status</th><th>Description</th>
            </tr>
          </thead>
          <tbody>{round_rows}</tbody>
        </table>
      </div>
    </section>

    <section class="panel">
      <h2>Applicants ({len(applications)})</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Roll number</th><th>Student</th>
              <th>Email</th><th>Application status</th>
            </tr>
          </thead>
          <tbody>{applicant_rows}</tbody>
        </table>
      </div>
    </section>

    {results_html}
    """

    return HTMLResponse(render_page("Manage Applications", content))


@router.post("/applications/{drive_id}/add-eligible")
def add_eligible_applicants(
    drive_id: int,
    request: Request,
    csrf_token: str = Form(..., max_length=100),
    db: Session = Depends(get_db),
):
    session, error = get_admin(request, db)
    if error:
        return error

    if not valid_csrf(session, csrf_token):
        return HTMLResponse(
            "Form expired. Reload and try again.",
            status_code=403,
        )

    drive = db.get(PlacementDrive, drive_id)
    if drive is None:
        return HTMLResponse("Placement drive not found.", status_code=404)

    students = db.scalars(
        select(Student).where(Student.is_active.is_(True))
    ).all()

    try:
        eligible, _ineligible = evaluate_students(students, drive)

        existing_ids = set(
            db.scalars(
                select(Application.student_id).where(
                    Application.drive_id == drive_id
                )
            ).all()
        )

        added = 0
        skipped = 0

        for item in eligible:
            student = _extract_student(item)

            if student is None:
                raise ValueError(
                    "Eligibility checker returned an invalid student result."
                )

            if student.id in existing_ids:
                skipped += 1
                continue

            db.add(
                Application(
                    student_id=student.id,
                    drive_id=drive_id,
                    status="applied",
                )
            )

            existing_ids.add(student.id)
            added += 1

        db.commit()

    except (SQLAlchemyError, ValueError):
        db.rollback()
        return HTMLResponse(
            "Could not add eligible students. No changes were saved. "
            "Check the server logs.",
            status_code=500,
        )

    return RedirectResponse(
        f"/applications/{drive_id}?added={added}&skipped={skipped}",
        status_code=303,
    )


@router.post("/applications/{drive_id}/rounds")
def create_recruitment_round(
    drive_id: int,
    request: Request,
    name: str = Form(..., max_length=100),
    scheduled_at: str = Form(""),
    description: str = Form("", max_length=2000),
    csrf_token: str = Form(..., max_length=100),
    db: Session = Depends(get_db),
):
    session, error = get_admin(request, db)
    if error:
        return error

    if not valid_csrf(session, csrf_token):
        return HTMLResponse(
            "Form expired. Reload and try again.",
            status_code=403,
        )

    drive = db.get(PlacementDrive, drive_id)
    if drive is None:
        return HTMLResponse("Placement drive not found.", status_code=404)

    name = " ".join(name.split())
    if not name:
        return HTMLResponse("Round name is required.", status_code=400)

    parsed_schedule = None

    if scheduled_at.strip():
        try:
            parsed_schedule = datetime.fromisoformat(scheduled_at)
        except ValueError:
            return HTMLResponse(
                "Invalid round date/time.",
                status_code=400,
            )

    last_number = db.scalar(
        select(func.max(RecruitmentRound.round_number)).where(
            RecruitmentRound.drive_id == drive_id
        )
    ) or 0

    rnd = RecruitmentRound(
        drive_id=drive_id,
        round_number=last_number + 1,
        name=name,
        scheduled_at=parsed_schedule,
        description=description.strip() or None,
        status="pending",
    )

    try:
        db.add(rnd)
        db.commit()
    except IntegrityError:
        db.rollback()
        return HTMLResponse(
            "Another round was created at the same time. Reload and try again.",
            status_code=409,
        )
    except SQLAlchemyError:
        db.rollback()
        return HTMLResponse(
            "Could not create the round.",
            status_code=500,
        )

    return RedirectResponse(
        f"/applications/{drive_id}",
        status_code=303,
    )


@router.post("/applications/{drive_id}/applicant/{application_id}/status")
def update_application_status(
    drive_id: int,
    application_id: int,
    request: Request,
    status: str = Form(...),
    csrf_token: str = Form(..., max_length=100),
    db: Session = Depends(get_db),
):
    session, error = get_admin(request, db)
    if error:
        return error

    if not valid_csrf(session, csrf_token):
        return HTMLResponse(
            "Form expired. Reload and try again.",
            status_code=403,
        )

    allowed = {
        "applied", "shortlisted", "rejected", "selected", "withdrawn"
    }

    if status not in allowed:
        return HTMLResponse("Invalid application status.", status_code=400)

    application = db.get(Application, application_id)

    if application is None or application.drive_id != drive_id:
        return HTMLResponse("Application not found.", status_code=404)

    old_status = application.status
    application.status = status

    try:
        if old_status != status:
            student = db.get(Student, application.student_id)
            drive = db.get(PlacementDrive, drive_id)

            if student and drive:
                db.add(
                    Notification(
                        student_id=student.id,
                        title="Placement application status updated",
                        message=(
                            f"Your application for {drive.company_name} — "
                            f"{drive.job_role} is now {status.title()}."
                        ),
                        category="placement",
                        is_read=False,
                    )
                )

        db.commit()

    except SQLAlchemyError:
        db.rollback()
        return HTMLResponse(
            "Could not update application status.",
            status_code=500,
        )

    return RedirectResponse(
        f"/applications/{drive_id}",
        status_code=303,
    )


@router.post("/applications/{drive_id}/result")
def save_round_result(
    drive_id: int,
    request: Request,
    application_id: int = Form(...),
    round_id: int = Form(...),
    result: str = Form(...),
    score: str = Form(""),
    remarks: str = Form("", max_length=1000),
    csrf_token: str = Form(..., max_length=100),
    db: Session = Depends(get_db),
):
    session, error = get_admin(request, db)
    if error:
        return error

    if not valid_csrf(session, csrf_token):
        return HTMLResponse(
            "Form expired. Reload and try again.",
            status_code=403,
        )

    if result not in {"pending", "passed", "failed", "absent"}:
        return HTMLResponse("Invalid round result.", status_code=400)

    application = db.get(Application, application_id)
    rnd = db.get(RecruitmentRound, round_id)

    if (
        application is None
        or rnd is None
        or application.drive_id != drive_id
        or rnd.drive_id != drive_id
    ):
        return HTMLResponse(
            "Application or round not found.",
            status_code=404,
        )

    parsed_score = None

    if score.strip():
        try:
            parsed_score = float(score)
        except ValueError:
            return HTMLResponse(
                "Score must be a number.",
                status_code=400,
            )

        if (
            not math.isfinite(parsed_score)
            or parsed_score < 0
            or parsed_score > 1000000
        ):
            return HTMLResponse(
                "Score is outside the allowed range.",
                status_code=400,
            )

    record = db.scalar(
        select(ApplicationRoundResult).where(
            ApplicationRoundResult.application_id == application_id,
            ApplicationRoundResult.round_id == round_id,
        )
    )

    old_result = record.result if record else None
    old_score = record.score if record else None
    old_remarks = record.remarks if record else None

    new_remarks = remarks.strip() or None

    if record is None:
        record = ApplicationRoundResult(
            application_id=application_id,
            round_id=round_id,
            result=result,
            score=parsed_score,
            remarks=new_remarks,
        )
        db.add(record)
        changed = True
    else:
        changed = (
            old_result != result
            or old_score != parsed_score
            or old_remarks != new_remarks
        )
        record.result = result
        record.score = parsed_score
        record.remarks = new_remarks

    try:
        # Notify the student only when the result actually changes.
        if changed:
            student = db.get(Student, application.student_id)

            if student:
                db.add(
                    Notification(
                        student_id=student.id,
                        title=f"Recruitment update: {rnd.name}",
                        message=(
                            f"Your result for {rnd.name} has been updated "
                            f"to {result.title()}."
                        ),
                        category="interview",
                        is_read=False,
                    )
                )

        db.commit()

    except SQLAlchemyError:
        db.rollback()
        return HTMLResponse(
            "Could not save the round result.",
            status_code=500,
        )

    return RedirectResponse(
        f"/applications/{drive_id}",
        status_code=303,
    )


@router.post("/applications/{drive_id}/apply")
def apply_to_drive(
    drive_id: int,
    request: Request,
    csrf_token: str = Form(..., max_length=100),
    db: Session = Depends(get_db),
):
    """Submit an application for an eligible published placement drive."""

    auth, error = get_logged_in_user(request, db)

    if error:
        return error

    session, user = auth

    if user.role != "student":
        return HTMLResponse(
            "Student access required.",
            status_code=403,
        )

    if not valid_csrf(session, csrf_token):
        return HTMLResponse(
            "Form expired. Reload the page and try again.",
            status_code=403,
        )

    student = db.scalar(
        select(Student).where(Student.email == user.email)
    )

    if student is None or not student.is_active:
        return HTMLResponse(
            "Active student record not found.",
            status_code=403,
        )

    drive = db.get(PlacementDrive, drive_id)

    if drive is None or drive.status != "published":
        return HTMLResponse(
            "This placement drive is not available.",
            status_code=404,
        )

    if (
        drive.application_deadline
        and drive.application_deadline < date.today()
    ):
        return RedirectResponse(
            "/drives",
            status_code=303,
        )

    existing = db.scalar(
        select(Application).where(
            Application.student_id == student.id,
            Application.drive_id == drive.id,
        )
    )

    if existing is not None:
        return RedirectResponse(
            "/drives?application=already_applied",
            status_code=303,
        )

    reasons = check_student(student, drive)

    if reasons:
        return RedirectResponse(
            "/drives?application=not_eligible",
            status_code=303,
        )

    try:
        application = Application(
            student_id=student.id,
            drive_id=drive.id,
            status="applied",
        )

        db.add(application)
        db.commit()

    except IntegrityError:
        db.rollback()

        # Another request may have submitted the application first.
        return RedirectResponse(
            "/drives?application=already_applied",
            status_code=303,
        )

    except SQLAlchemyError:
        db.rollback()

        return RedirectResponse(
            "/drives?application=error",
            status_code=303,
        )

    return RedirectResponse(
        "/drives?application=success",
        status_code=303,
    )
