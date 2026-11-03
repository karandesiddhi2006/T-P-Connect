
import html
import hmac
import math
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Application, PlacementDrive, Student, User
from app.routers.eligibility import check_student
from app.security import SESSION_COOKIE, find_session

router = APIRouter()


def esc(value):
    return html.escape(str(value), quote=True)


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

    return (session, user), None


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


def valid_csrf(session, csrf_token):
    return bool(
        csrf_token
        and hmac.compare_digest(session.csrf_token, csrf_token)
    )


def render_page(title: str, content: str, role: str = "admin") -> str:
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{esc(title)} | T&P Connect</title>
      <style>
        body {{
          font-family: Arial, sans-serif;
          background: #f4f6fa;
          color: #202b3c;
          margin: 0;
          padding: 28px;
        }}
        main {{ max-width: 1200px; margin: auto; }}
        .panel {{
          background: white;
          padding: 24px;
          margin: 18px 0;
          border-radius: 12px;
          box-shadow: 0 2px 10px #0000000a;
        }}
        input, textarea, select {{
          box-sizing: border-box;
          display: block;
          width: 100%;
          padding: 10px;
          margin: 6px 0 16px;
          border: 1px solid #ccd3df;
          border-radius: 6px;
        }}
        label {{ font-weight: 600; }}
        button, .button {{
          background: #234bc7;
          color: white;
          border: 0;
          border-radius: 6px;
          padding: 10px 13px;
          cursor: pointer;
          text-decoration: none;
          display: inline-block;
          font-size: 14px;
        }}
        button:disabled {{
          opacity: 0.6;
          cursor: not-allowed;
        }}
        .secondary {{ background: #475569; }}
        .warning {{ background: #a16207; }}
        .danger {{ background: #b91c1c; }}
        .success {{ background: #15803d; }}
        .muted {{ color: #64748b; }}
        .notice {{
          background: #fff7ed;
          border: 1px solid #fed7aa;
          border-radius: 8px;
          padding: 12px 16px;
        }}
        .table-wrap {{ overflow-x: auto; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{
          text-align: left;
          padding: 12px;
          border-bottom: 1px solid #e5e9f0;
          vertical-align: top;
        }}
        th {{ background: #f8fafc; }}
        .actions {{
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          align-items: center;
        }}
        .actions form {{ margin: 0; }}
        .actions button {{ white-space: nowrap; }}
        .status {{
          display: inline-block;
          padding: 5px 9px;
          border-radius: 5px;
          font-weight: bold;
          text-transform: capitalize;
        }}
        .draft {{ background: #e2e8f0; color: #334155; }}
        .published {{ background: #dcfce7; color: #166534; }}
        .archived {{ background: #fee2e2; color: #991b1b; }}
      </style>
    </head>
    <body>
      <main>
        <p>
          <a href="/dashboard">Dashboard</a> ·
          <a href="/drives">Placement Drives</a>
          {(
              ' · <a href="/students">Student Records</a>'
              ' · <a href="/circular-analyzer">Circular Analyzer</a>'
              if role == "admin" else ""
          )}
        </p>
        {content}
      </main>
    </body>
    </html>
    """


@router.get("/drives", response_class=HTMLResponse)
def list_drives(
    request: Request,
    view: str = "active",
    db: Session = Depends(get_db),
):
    auth, error_response = get_logged_in_user(request, db)

    if error_response:
        return error_response

    current, user = auth

    # -------------------------------------------------
    # STUDENT PLACEMENT DRIVES
    # -------------------------------------------------
    if user.role == "student":

        student = db.scalar(
            select(Student).where(Student.email == user.email)
        )

        if student is None or not student.is_active:
            return HTMLResponse(
                "Active student record not found.",
                status_code=403,
            )

        published_drives = db.scalars(
            select(PlacementDrive)
            .where(PlacementDrive.status == "published")
            .order_by(PlacementDrive.created_at.desc())
        ).all()

        notice_messages = {
            "success": "Your application was submitted successfully!",
            "already_applied": (
                "You have already applied to this drive. "
                "Your application status is shown below."
            ),
            "not_eligible": (
                "You are not eligible for one or more placement drives. "
                "Check the eligibility reasons shown below."
            ),
            "error": (
                "We could not submit your application. Please try again."
            ),
        }

        notice_key = request.query_params.get("application", "")
        notice = notice_messages.get(notice_key, "")

        notice_html = (
            f'<div class="notice">{esc(notice)}</div>'
            if notice else ""
        )

        rows = ""

        for drive in published_drives:

            branches = ", ".join(drive.eligible_branches or [])

            package = (
                f"{drive.package_lpa:.2f} LPA"
                if drive.package_lpa is not None
                else "Not specified"
            )

            deadline = (
                drive.application_deadline.isoformat()
                if drive.application_deadline
                else "Not specified"
            )

            existing_application = db.scalar(
                select(Application).where(
                    Application.student_id == student.id,
                    Application.drive_id == drive.id,
                )
            )

            if existing_application:

                application_status = (
                    existing_application.status or "applied"
                ).replace("_", " ").title()

                action_html = f"""
                <span style="
                    display:inline-block;
                    padding:8px 12px;
                    border-radius:6px;
                    background:#dcfce7;
                    color:#166534;
                    font-weight:bold;">
                    {esc(application_status)}
                </span>
                """

            elif (
                drive.application_deadline
                and drive.application_deadline < date.today()
            ):

                action_html = """
                <span style="
                    display:inline-block;
                    padding:8px 12px;
                    border-radius:6px;
                    background:#fee2e2;
                    color:#991b1b;
                    font-weight:bold;">
                    Applications Closed
                </span>
                """

            else:

                reasons = check_student(student, drive)

                if reasons:

                    reason_items = "".join(
                        f"<li>{esc(reason)}</li>"
                        for reason in reasons
                    )

                    action_html = f"""
                    <span style="
                        display:inline-block;
                        padding:7px 10px;
                        border-radius:6px;
                        background:#fee2e2;
                        color:#991b1b;
                        font-weight:bold;">
                        Not Eligible
                    </span>
                    <details style="margin-top:8px; min-width:150px;">
                      <summary style="cursor:pointer;">
                        View reasons
                      </summary>
                      <ul>{reason_items}</ul>
                    </details>
                    """

                else:

                    action_html = f"""
                    <form method="post"
                          action="/applications/{drive.id}/apply"
                          onsubmit="
                            const button = this.querySelector('button');
                            button.disabled = true;
                            button.textContent = 'Submitting...';
                          ">
                      <input type="hidden" name="csrf_token"
                             value="{esc(current.csrf_token)}">
                      <button type="submit">Apply</button>
                    </form>
                    """

            rows += f"""
            <tr>
              <td>{esc(drive.company_name)}</td>
              <td>{esc(drive.job_role)}</td>
              <td>{esc(package)}</td>
              <td>{drive.minimum_cgpa:.2f}</td>
              <td>{esc(branches)}</td>
              <td>{drive.graduation_year}</td>
              <td>{esc(deadline)}</td>
              <td>{action_html}</td>
            </tr>
            """

        if not rows:
            rows = """
            <tr>
              <td colspan="8">
                No published placement drives are available yet.
              </td>
            </tr>
            """

        content = f"""
        <h1>Available Placement Drives</h1>

        <p class="muted">
          Only opportunities published by the Training and
          Placement Cell are shown here.
        </p>

        {notice_html}

        <section class="panel">
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Role</th>
                  <th>Package</th>
                  <th>Minimum CGPA</th>
                  <th>Eligible Branches</th>
                  <th>Graduation Year</th>
                  <th>Application Deadline</th>
                  <th>Action / Status</th>
                </tr>
              </thead>
              <tbody>{rows}</tbody>
            </table>
          </div>
        </section>
        """

        return HTMLResponse(
            render_page(
                "Available Placement Drives",
                content,
                role="student",
            )
        )

    # -------------------------------------------------
    # ADMIN PLACEMENT DRIVES
    # THIS SECTION WAS MISSING IN THE PREVIOUS CODE
    # -------------------------------------------------
    if user.role != "admin":
        return HTMLResponse("Access denied.", status_code=403)

    show_archived = view == "archived"

    statement = select(PlacementDrive)

    if show_archived:
        statement = statement.where(
            PlacementDrive.status == "archived"
        )
    else:
        statement = statement.where(
            PlacementDrive.status != "archived"
        )

    drives = db.scalars(
        statement.order_by(PlacementDrive.created_at.desc())
    ).all()

    rows = ""

    for drive in drives:

        branches = ", ".join(drive.eligible_branches or [])

        package = (
            f"{drive.package_lpa:.2f} LPA"
            if drive.package_lpa is not None
            else "Not specified"
        )

        deadline = (
            drive.application_deadline.isoformat()
            if drive.application_deadline
            else "Not specified"
        )

        status = (drive.status or "draft").lower()

        status_html = (
            f'<span class="status {esc(status)}">'
            f'{esc(status.title())}</span>'
        )

        actions = ""

        if status == "draft":

            actions += f"""
            <form method="post"
                  action="/drives/{drive.id}/publish">
              <input type="hidden" name="csrf_token"
                     value="{esc(current.csrf_token)}">
              <button type="submit" class="success">
                Publish
              </button>
            </form>

            <form method="post"
                  action="/drives/{drive.id}/delete"
                  onsubmit="return confirm(
                    'Permanently delete this draft drive?'
                  );">
              <input type="hidden" name="csrf_token"
                     value="{esc(current.csrf_token)}">
              <button type="submit" class="danger">
                Delete Draft
              </button>
            </form>
            """

        elif status == "published":

            actions += f"""
            <form method="post"
                  action="/drives/{drive.id}/unpublish">
              <input type="hidden" name="csrf_token"
                     value="{esc(current.csrf_token)}">
              <button type="submit" class="secondary">
                Unpublish
              </button>
            </form>
            """

        if status != "archived":

            actions += f"""
            <form method="post"
                  action="/drives/{drive.id}/archive"
                  onsubmit="return confirm(
                    'Archive this placement drive?'
                  );">
              <input type="hidden" name="csrf_token"
                     value="{esc(current.csrf_token)}">
              <button type="submit" class="warning">
                Archive
              </button>
            </form>
            """

        else:

            actions += f"""
            <form method="post"
                  action="/drives/{drive.id}/restore">
              <input type="hidden" name="csrf_token"
                     value="{esc(current.csrf_token)}">
              <button type="submit" class="secondary">
                Restore as Draft
              </button>
            </form>
            """

        rows += f"""
        <tr>
          <td>{esc(drive.company_name)}</td>
          <td>{esc(drive.job_role)}</td>
          <td>{esc(package)}</td>
          <td>{drive.minimum_cgpa:.2f}</td>
          <td>{esc(branches)}</td>
          <td>{drive.graduation_year}</td>
          <td>{esc(deadline)}</td>
          <td>{status_html}</td>
          <td>
            <div class="actions">
              {actions}
            </div>
          </td>
        </tr>
        """

    if not rows:
        empty_message = (
            "No archived placement drives found."
            if show_archived
            else "No placement drives found. Create your first drive below."
        )

        rows = f"""
        <tr>
          <td colspan="9">{esc(empty_message)}</td>
        </tr>
        """

    archived_link = (
        '<a class="button secondary" href="/drives">'
        'View Active Drives</a>'
        if show_archived
        else
        '<a class="button secondary" href="/drives?view=archived">'
        'View Archived Drives</a>'
    )

    content = f"""
    <h1>Placement Drives Management</h1>

    <p class="muted">
      Create, publish, manage and archive company placement drives.
    </p>

    <section class="panel">
      <h2>{'Archived Drives' if show_archived else 'Active Drives'}</h2>

      <p>{archived_link}</p>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Company</th>
              <th>Job Role</th>
              <th>Package</th>
              <th>Minimum CGPA</th>
              <th>Eligible Branches</th>
              <th>Graduation Year</th>
              <th>Deadline</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </section>
    """

    if not show_archived:

        content += f"""
        <section class="panel">
          <h2>Create Placement Drive</h2>

          <p class="muted">
            Newly created drives are saved as drafts.
            Students cannot see them until you publish them.
          </p>

          <form method="post" action="/drives">

            <input type="hidden" name="csrf_token"
                   value="{esc(current.csrf_token)}">

            <label>Company Name</label>
            <input name="company_name" maxlength="150"
                   placeholder="Example: Infosys" required>

            <label>Job Role</label>
            <input name="job_role" maxlength="150"
                   placeholder="Example: Graduate Engineer Trainee"
                   required>

            <label>Package (LPA)</label>
            <input name="package_lpa" type="number"
                   min="0" max="1000" step="0.01"
                   placeholder="Example: 6">

            <label>Minimum CGPA</label>
            <input name="minimum_cgpa" type="number"
                   min="0" max="10" step="0.01"
                   required>

            <label>Eligible Branches</label>
            <input name="eligible_branches"
                   maxlength="500"
                   placeholder="CSE, AI&ML, IT"
                   required>

            <label>Graduation Year</label>
            <input name="graduation_year" type="number"
                   min="2020" max="2100" required>

            <label>Maximum Active Backlogs</label>
            <input name="maximum_active_backlogs"
                   type="number" min="0" max="100"
                   value="0" required>

            <label>Maximum Total Backlogs</label>
            <input name="maximum_total_backlogs"
                   type="number" min="0" max="100"
                   value="0" required>

            <label>Application Deadline</label>
            <input name="application_deadline"
                   type="date">

            <label>Job Description</label>
            <textarea name="description"
                      maxlength="5000"
                      rows="4"
                      placeholder="Enter job description and other details"></textarea>

            <button type="submit">Save as Draft</button>
          </form>
        </section>
        """

    return HTMLResponse(
        render_page("Placement Drives Management", content)
    )


@router.post("/drives")
def create_drive(
    request: Request,
    company_name: str = Form(..., max_length=150),
    job_role: str = Form(..., max_length=150),
    package_lpa: str = Form(""),
    minimum_cgpa: float = Form(...),
    eligible_branches: str = Form(..., max_length=500),
    graduation_year: int = Form(...),
    maximum_active_backlogs: int = Form(0),
    maximum_total_backlogs: int = Form(0),
    application_deadline: str = Form(""),
    description: str = Form("", max_length=5000),
    csrf_token: str = Form(..., max_length=100),
    db: Session = Depends(get_db),
):
    auth, error_response = get_admin(request, db)

    if error_response:
        return error_response

    current, user = auth

    if not valid_csrf(current, csrf_token):
        return HTMLResponse(
            "Form expired. Reload the page and try again.",
            status_code=403,
        )

    company_name = " ".join(company_name.split())
    job_role = " ".join(job_role.split())

    branches = list(dict.fromkeys(
        branch.strip()
        for branch in eligible_branches.split(",")
        if branch.strip()
    ))

    if not company_name or not job_role or not branches:
        return HTMLResponse(
            "Company, role, and branches are required.",
            status_code=400,
        )

    if (
        not math.isfinite(minimum_cgpa)
        or not 0 <= minimum_cgpa <= 10
    ):
        return HTMLResponse(
            "Minimum CGPA must be between 0 and 10.",
            status_code=400,
        )

    if not 2020 <= graduation_year <= 2100:
        return HTMLResponse(
            "Invalid graduation year.",
            status_code=400,
        )

    if not (
        0 <= maximum_active_backlogs
        <= maximum_total_backlogs
        <= 100
    ):
        return HTMLResponse(
            "Backlog limits must satisfy "
            "0 <= active <= total <= 100.",
            status_code=400,
        )

    package = None

    if package_lpa.strip():
        try:
            package = float(package_lpa)
        except ValueError:
            return HTMLResponse(
                "Package must be a valid number.",
                status_code=400,
            )

        if not math.isfinite(package) or not 0 <= package <= 1000:
            return HTMLResponse(
                "Package must be between 0 and 1000 LPA.",
                status_code=400,
            )

    deadline = None

    if application_deadline.strip():
        try:
            deadline = date.fromisoformat(application_deadline)
        except ValueError:
            return HTMLResponse(
                "Enter a valid application deadline.",
                status_code=400,
            )

    drive = PlacementDrive(
        company_name=company_name,
        job_role=job_role,
        package_lpa=package,
        minimum_cgpa=minimum_cgpa,
        eligible_branches=branches,
        graduation_year=graduation_year,
        maximum_active_backlogs=maximum_active_backlogs,
        maximum_total_backlogs=maximum_total_backlogs,
        application_deadline=deadline,
        description=description.strip() or None,
        status="draft",
        created_by=user.id,
    )

    try:
        db.add(drive)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return RedirectResponse("/drives", status_code=303)


def update_drive_status(
    request: Request,
    drive_id: int,
    csrf_token: str,
    action: str,
    db: Session,
):
    auth, error_response = get_admin(request, db)

    if error_response:
        return error_response

    current, user = auth

    if not valid_csrf(current, csrf_token):
        return HTMLResponse(
            "Form expired. Reload the page and try again.",
            status_code=403,
        )

    drive = db.get(PlacementDrive, drive_id)

    if drive is None:
        return HTMLResponse(
            "Placement drive not found.",
            status_code=404,
        )

    if action == "archive":
        if drive.status == "archived":
            return RedirectResponse(
                "/drives?view=archived", status_code=303
            )

        drive.status = "archived"

    elif action == "restore":
        if drive.status != "archived":
            return RedirectResponse("/drives", status_code=303)

        drive.status = "draft"

    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return HTMLResponse(
            "Could not update this drive. Check the server logs.",
            status_code=500,
        )

    destination = (
        "/drives?view=archived"
        if action == "archive"
        else "/drives"
    )

    return RedirectResponse(destination, status_code=303)


@router.post("/drives/{drive_id}/publish")
def publish_drive(
    drive_id: int,
    request: Request,
    csrf_token: str = Form(..., max_length=100),
    db: Session = Depends(get_db),
):
    auth, error_response = get_admin(request, db)

    if error_response:
        return error_response

    current, _user = auth

    if not valid_csrf(current, csrf_token):
        return HTMLResponse("Invalid CSRF token.", status_code=403)

    drive = db.get(PlacementDrive, drive_id)

    if drive is None:
        return HTMLResponse(
            "Placement drive not found.", status_code=404
        )

    if drive.status != "draft":
        return HTMLResponse(
            "Only draft drives can be published.", status_code=400
        )

    drive.status = "published"

    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return HTMLResponse(
            "Could not publish this drive.", status_code=500
        )

    return RedirectResponse("/drives", status_code=303)


@router.post("/drives/{drive_id}/unpublish")
def unpublish_drive(
    drive_id: int,
    request: Request,
    csrf_token: str = Form(..., max_length=100),
    db: Session = Depends(get_db),
):
    auth, error_response = get_admin(request, db)

    if error_response:
        return error_response

    current, _user = auth

    if not valid_csrf(current, csrf_token):
        return HTMLResponse("Invalid CSRF token.", status_code=403)

    drive = db.get(PlacementDrive, drive_id)

    if drive is None:
        return HTMLResponse(
            "Placement drive not found.", status_code=404
        )

    if drive.status != "published":
        return HTMLResponse(
            "Only published drives can be unpublished.",
            status_code=400,
        )

    drive.status = "draft"

    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return HTMLResponse(
            "Could not unpublish this drive.", status_code=500
        )

    return RedirectResponse("/drives", status_code=303)


@router.post("/drives/{drive_id}/archive")
def archive_drive(
    drive_id: int,
    request: Request,
    csrf_token: str = Form(..., max_length=100),
    db: Session = Depends(get_db),
):
    return update_drive_status(
        request, drive_id, csrf_token, "archive", db
    )


@router.post("/drives/{drive_id}/restore")
def restore_drive(
    drive_id: int,
    request: Request,
    csrf_token: str = Form(..., max_length=100),
    db: Session = Depends(get_db),
):
    return update_drive_status(
        request, drive_id, csrf_token, "restore", db
    )


@router.post("/drives/{drive_id}/delete")
def delete_draft_drive(
    drive_id: int,
    request: Request,
    csrf_token: str = Form(..., max_length=100),
    db: Session = Depends(get_db),
):
    auth, error_response = get_admin(request, db)

    if error_response:
        return error_response

    current, user = auth

    if not valid_csrf(current, csrf_token):
        return HTMLResponse(
            "Form expired. Reload the page and try again.",
            status_code=403,
        )

    drive = db.get(PlacementDrive, drive_id)

    if drive is None:
        return HTMLResponse(
            "Placement drive not found.", status_code=404
        )

    if drive.status != "draft":
        return HTMLResponse(
            "Only draft drives can be permanently deleted. "
            "Archive other drives instead.",
            status_code=400,
        )

    try:
        db.delete(drive)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return HTMLResponse(
            "This drive could not be deleted. It may be linked to other "
            "records. The deletion was rolled back; archive the drive "
            "instead and check the server logs.",
            status_code=409,
        )

    return RedirectResponse("/drives", status_code=303)
