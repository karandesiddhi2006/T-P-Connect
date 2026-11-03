
import html
import hmac

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PlacementDrive, Student, User
from app.routers.eligibility import evaluate_students
from app.security import (
    SESSION_COOKIE,
    cookie_options,
    create_session,
    find_session,
    verify_password,
)

router = APIRouter()


# ---------------------------------------------------------
# LOGIN PAGE HTML
# ---------------------------------------------------------

def login_page(csrf_token: str, role: str, error: str = "") -> str:
    safe_token = html.escape(csrf_token, quote=True)
    safe_error = html.escape(error)

    is_admin = role == "admin"
    title = "Administrator Login" if is_admin else "Student Login"

    description = (
        "Sign in to manage placement operations and student records."
        if is_admin
        else "Sign in to explore placement drives and track your applications."
    )

    action = f"/{role}/login"

    error_html = (
        f'<div class="error" role="alert">{safe_error}</div>'
        if error else ""
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} | T&amp;P Connect</title>

<style>
*{{box-sizing:border-box}}

body{{
    margin:0;
    font-family:Inter,Segoe UI,Arial,sans-serif;
    background:#f3f6fb;
    color:#172033;
    min-height:100vh;
    display:grid;
    place-items:center;
    padding:24px
}}

.card{{
    background:white;
    width:100%;
    max-width:430px;
    padding:36px;
    border:1px solid #e3e9f2;
    border-radius:18px;
    box-shadow:0 12px 40px #1720330d
}}

.brand{{
    display:flex;
    align-items:center;
    gap:12px;
    margin-bottom:30px
}}

.logo{{
    background:#2457d6;
    color:white;
    padding:12px;
    border-radius:12px;
    font-weight:800
}}

h1{{font-size:23px;margin:0}}

.sub{{
    color:#64748b;
    margin:7px 0 26px;
    line-height:1.6
}}

label{{
    display:block;
    font-size:14px;
    font-weight:600;
    margin:18px 0 8px
}}

input{{
    width:100%;
    padding:13px;
    border:1px solid #d6deeb;
    border-radius:9px;
    font-size:15px;
    margin-top:8px
}}

input:focus{{
    outline:2px solid #b9ccff;
    border-color:#2457d6
}}

button{{
    width:100%;
    padding:14px;
    margin-top:24px;
    border:0;
    border-radius:9px;
    background:#2457d6;
    color:white;
    font-weight:700;
    font-size:15px;
    cursor:pointer
}}

button:hover{{background:#1945b5}}

.error{{
    background:#fff1f2;
    color:#b42336;
    padding:12px;
    border-radius:8px;
    font-size:14px
}}

.note{{
    font-size:12px;
    color:#94a3b8;
    text-align:center;
    margin-top:24px
}}

.back{{
    display:block;
    text-align:center;
    margin-top:18px;
    font-size:13px;
    color:#2457d6;
    text-decoration:none
}}
</style>
</head>

<body>
<main class="card">

<div class="brand">
    <div class="logo">TP</div>
    <div>
        <h1>T&amp;P Connect</h1>
        <div style="font-size:13px;color:#64748b;margin-top:4px">
            Placement Management Portal
        </div>
    </div>
</div>

<h2>{title}</h2>
<p class="sub">{description}</p>

{error_html}

<form method="post" action="{action}">

    <input type="hidden" name="csrf_token" value="{safe_token}">

    <label for="email">Email address</label>
    <input
        id="email"
        type="email"
        name="email"
        required
        maxlength="255"
        autocomplete="username"
    >

    <label for="password">Password</label>
    <input
        id="password"
        type="password"
        name="password"
        required
        maxlength="128"
        autocomplete="current-password"
    >

    <button type="submit">Sign in securely</button>

</form>

<a class="back" href="/">← Back to portal selection</a>

<div class="note">Authorized users only</div>

</main>
</body>
</html>"""


# ---------------------------------------------------------
# COMMON LOGIN PAGE HANDLER
# ---------------------------------------------------------

def show_login(request: Request, db: Session, role: str):

    current = find_session(
        db, request.cookies.get(SESSION_COOKIE)
    )

    if current and current.user_id:
        user = db.get(User, current.user_id)

        if user and user.is_active:
            return RedirectResponse("/dashboard", status_code=303)

        db.delete(current)
        db.commit()

    if current is None:
        raw_token, current = create_session(db)

        response = HTMLResponse(
            login_page(current.csrf_token, role)
        )

        response.set_cookie(
            value=raw_token,
            **cookie_options()
        )

        return response

    return HTMLResponse(
        login_page(current.csrf_token, role)
    )


# ---------------------------------------------------------
# ADMIN AND STUDENT LOGIN PAGE ROUTES
# ---------------------------------------------------------

@router.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(
    request: Request,
    db: Session = Depends(get_db),
):
    return show_login(request, db, "admin")


@router.get("/student/login", response_class=HTMLResponse)
def student_login_page(
    request: Request,
    db: Session = Depends(get_db),
):
    return show_login(request, db, "student")


# Old login URL compatibility
@router.get("/login")
def legacy_login():
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------
# COMMON LOGIN AUTHENTICATION
# ---------------------------------------------------------

def process_login(
    request: Request,
    email: str,
    password: str,
    csrf_token: str,
    expected_role: str,
    db: Session,
):

    current = find_session(
        db, request.cookies.get(SESSION_COOKIE)
    )

    if current is None or not hmac.compare_digest(
        current.csrf_token, csrf_token
    ):
        return HTMLResponse(
            "Login form expired. Please reload the login page.",
            status_code=403,
        )

    user = db.scalar(
        select(User).where(
            User.email == email.strip().lower()
        )
    )

    if (
        user is None
        or not user.is_active
        or user.role != expected_role
        or not verify_password(password, user.password_hash)
    ):
        return HTMLResponse(
            login_page(
                current.csrf_token,
                expected_role,
                "Invalid email, password, or account type.",
            ),
            status_code=401,
        )

    # Delete old anonymous session.
    db.delete(current)
    db.commit()

    # Create authenticated session.
    raw_token, _ = create_session(db, user.id)

    response = RedirectResponse(
        "/dashboard",
        status_code=303
    )

    response.set_cookie(
        value=raw_token,
        **cookie_options()
    )

    return response


# ---------------------------------------------------------
# ADMIN LOGIN
# ---------------------------------------------------------

@router.post("/admin/login", response_class=HTMLResponse)
def admin_login(
    request: Request,
    email: str = Form(..., max_length=255),
    password: str = Form(..., max_length=128),
    csrf_token: str = Form(..., max_length=100),
    db: Session = Depends(get_db),
):

    return process_login(
        request,
        email,
        password,
        csrf_token,
        "admin",
        db,
    )


# ---------------------------------------------------------
# STUDENT LOGIN
# ---------------------------------------------------------

@router.post("/student/login", response_class=HTMLResponse)
def student_login(
    request: Request,
    email: str = Form(..., max_length=255),
    password: str = Form(..., max_length=128),
    csrf_token: str = Form(..., max_length=100),
    db: Session = Depends(get_db),
):

    return process_login(
        request,
        email,
        password,
        csrf_token,
        "student",
        db,
    )


# Old POST login compatibility: Admin login
@router.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    email: str = Form(..., max_length=255),
    password: str = Form(..., max_length=128),
    csrf_token: str = Form(..., max_length=100),
    db: Session = Depends(get_db),
):

    return process_login(
        request,
        email,
        password,
        csrf_token,
        "admin",
        db,
    )


# ---------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
):

    current = find_session(
        db, request.cookies.get(SESSION_COOKIE)
    )

    if current is None or current.user_id is None:
        return RedirectResponse("/", status_code=303)

    user = db.get(User, current.user_id)

    if user is None or not user.is_active:

        db.delete(current)
        db.commit()

        response = RedirectResponse("/", status_code=303)
        response.delete_cookie(SESSION_COOKIE, path="/")

        return response

    # -----------------------------------------------------
    # ROLE-BASED DASHBOARD CONTENT
    # -----------------------------------------------------

    if user.role == "admin":

        heading = "Administrator Dashboard"

        description = (
            "Manage student records, placement drives and eligibility."
        )

        role_label = "T&P ADMINISTRATOR"

        modules = [
            ("Student Records", "Import and manage student profiles."),
            ("Circular Analyzer", "Upload a company PDF and extract placement criteria."),
            ("Placement Drives", "Review and manage saved placement drives."),
            ("Eligibility Checker", "Evaluate students against approved rules."),
            ("Applications", "Track student applications and rounds."),
        ]

        banner_title = "Welcome to your T&P management workspace"

        banner_description = (
            "Manage student information, analyze company requirements, "
            "publish placement drives, verify eligibility and monitor "
            "student recruitment progress from one place."
        )

        section_title = "Placement management"

        section_description = (
            "Access your placement operations and management tools."
        )

        quick_actions_html = """
        <a class="quick-action primary" href="/students">
            + Manage Students
        </a>

        <a class="quick-action" href="/drives">
            Manage Placement Drives
        </a>

        <a class="quick-action" href="/circular-analyzer">
            Analyze Company Circular
        </a>

        <a class="quick-action" href="/applications">
            View Applications
        </a>
        """

    elif user.role == "student":

        heading = "Student Dashboard"

        description = (
            "Explore placement opportunities and track your progress."
        )

        role_label = "STUDENT"

        modules = [
            ("My Profile", "Academic profile and eligibility details."),
            ("Placement Drives", "Explore available opportunities."),
            ("My Applications", "Track your application progress."),
            ("Notifications", "Placement updates and announcements."),
        ]

        banner_title = "Welcome to your student workspace"

        banner_description = (
            "Explore published placement opportunities, review your "
            "eligibility, track recruitment progress and stay updated "
            "with important placement notifications."
        )

        section_title = "Your placement workspace"

        section_description = (
            "Everything you need to stay updated with placement activities."
        )

        quick_actions_html = """
        <a class="quick-action primary" href="/drives">
            Explore Placement Drives
        </a>

        <a class="quick-action" href="/student/applications">
            Track Applications
        </a>

        <a class="quick-action" href="/notifications">
            View Notifications
        </a>
        """

    else:

        return HTMLResponse(
            "Account role is not configured.",
            status_code=403
        )

    # -----------------------------------------------------
    # ADMIN DASHBOARD LIVE STATISTICS
    # -----------------------------------------------------

    stats_html = ""

    if user.role == "admin":

        active_students_count = db.scalar(
            select(func.count())
            .select_from(Student)
            .where(Student.is_active.is_(True))
        ) or 0

        all_students_count = db.scalar(
            select(func.count()).select_from(Student)
        ) or 0

        total_drives_count = db.scalar(
            select(func.count()).select_from(PlacementDrive)
        ) or 0

        draft_drives_count = db.scalar(
            select(func.count())
            .select_from(PlacementDrive)
            .where(PlacementDrive.status == "draft")
        ) or 0

        latest_drive = db.scalar(
            select(PlacementDrive)
            .where(PlacementDrive.status == "published")
            .order_by(PlacementDrive.created_at.desc())
            .limit(1)
        )

        eligible_count = 0
        ineligible_count = 0

        if latest_drive is not None:

            active_students = db.scalars(
                select(Student).where(
                    Student.is_active.is_(True)
                )
            ).all()

            eligible_students, ineligible_students = evaluate_students(
                active_students,
                latest_drive
            )

            eligible_count = len(eligible_students)
            ineligible_count = len(ineligible_students)

        stats = [
            (
                "Active Students",
                active_students_count,
                f"{all_students_count} student records in total"
            ),
            (
                "Placement Drives",
                total_drives_count,
                "All drives saved in the system"
            ),
            (
                "Draft Drives",
                draft_drives_count,
                "Drives not yet published"
            ),
            (
                "Eligible Students",
                eligible_count,
                f"Based on {latest_drive.company_name}"
                if latest_drive else
                "Create a drive to calculate eligibility"
            ),
            (
                "Ineligible Students",
                ineligible_count,
                f"Based on {latest_drive.company_name}"
                if latest_drive else
                "Create a drive to calculate eligibility"
            ),
        ]

        stat_cards = []

        for label, value, note in stats:

            stat_cards.append(
                f'<article class="stat-card">'
                f'<div class="stat-label">{html.escape(label)}</div>'
                f'<div class="stat-value">{int(value)}</div>'
                f'<div class="stat-note">{html.escape(note)}</div>'
                f'</article>'
            )

        stats_html = (
            '<section class="stats" aria-label="Live placement statistics">'
            + "".join(stat_cards)
            + '</section>'
        )

    # -----------------------------------------------------
    # SAFE DISPLAY VALUES
    # -----------------------------------------------------

    safe_heading = html.escape(heading)
    safe_description = html.escape(description)
    safe_email = html.escape(user.email)
    safe_role = html.escape(role_label)
    safe_csrf = html.escape(current.csrf_token, quote=True)

    safe_banner_title = html.escape(banner_title)
    safe_banner_description = html.escape(banner_description)
    safe_section_title = html.escape(section_title)
    safe_section_description = html.escape(section_description)

    # -----------------------------------------------------
    # MODULE LINKS
    # -----------------------------------------------------

    if user.role == "admin":

        module_links = {
            "Student Records": "/students",
            "Circular Analyzer": "/circular-analyzer",
            "Placement Drives": "/drives",
            "Eligibility Checker": "/eligibility",
            "Applications": "/applications",
        }

    else:

        module_links = {
            "My Profile": "/student/profile",
            "Placement Drives": "/drives",
            "My Applications": "/student/applications",
            "Notifications": "/notifications",
        }

    module_cards = ""

    for index, (name, detail) in enumerate(modules, start=1):

        safe_name = html.escape(name)
        safe_detail = html.escape(detail)

        target = module_links.get(name)

        if target:

            module_cards += f"""
            <a class="module module-link" href="{target}">
              <div class="module-icon">{index:02d}</div>
              <div class="module-content">
                <h3>{safe_name}</h3>
                <p>{safe_detail}</p>
                <span class="status status-ready">Open module →</span>
              </div>
            </a>
            """

        else:

            module_cards += f"""
            <article class="module">
              <div class="module-icon">{index:02d}</div>
              <div class="module-content">
                <h3>{safe_name}</h3>
                <p>{safe_detail}</p>
                <span class="status">Coming soon</span>
              </div>
            </article>
            """

    # -----------------------------------------------------
    # SIDEBAR
    # -----------------------------------------------------

    admin_sidebar_links = (
        '<a class="nav-item" href="/students">Student Records</a>'
        '<a class="nav-item" href="/circular-analyzer">Circular Analyzer</a>'
        '<a class="nav-item" href="/drives">Placement Drives</a>'
        '<a class="nav-item" href="/eligibility">Eligibility Checker</a>'
        '<a class="nav-item" href="/applications">Applications</a>'
        '<a class="nav-item" href="/notifications/admin">Notifications</a>'
        if user.role == "admin" else
        '<a class="nav-item" href="/student/profile">My Profile</a>'
        '<a class="nav-item" href="/drives">Placement Drives</a>'
        '<a class="nav-item" href="/student/applications">My Applications</a>'
        '<a class="nav-item" href="/notifications">Notifications</a>'
    )

    # -----------------------------------------------------
    # DASHBOARD HTML
    # -----------------------------------------------------

    return HTMLResponse(f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_heading} | T&amp;P Connect</title>

<style>
* {{
    box-sizing: border-box;
}}

body {{
    margin: 0;
    background: #f4f7fb;
    color: #18243a;
    font-family: Inter, Segoe UI, Arial, sans-serif;
}}

.layout {{
    display: flex;
    min-height: 100vh;
}}

.sidebar {{
    width: 250px;
    background: #172747;
    color: white;
    padding: 26px 18px;
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
}}

.brand {{
    display: flex;
    align-items: center;
    gap: 11px;
    padding: 0 8px 30px;
}}

.logo {{
    background: #4779f5;
    padding: 11px;
    border-radius: 10px;
    font-weight: 800;
}}

.brand-name {{
    font-size: 17px;
    font-weight: 750;
}}

.brand-sub {{
    font-size: 11px;
    color: #aebbd3;
    margin-top: 4px;
}}

.nav-label {{
    font-size: 10px;
    letter-spacing: 1.5px;
    color: #91a2c0;
    padding: 12px 10px;
}}

.sidebar nav {{
    display: flex;
    flex-direction: column;
}}

.nav-item {{
    padding: 12px 13px;
    border-radius: 8px;
    margin: 3px 0;
    font-size: 13px;
    color: #d9e2f3;
    display: block;
    text-decoration: none;
    transition: background .2s, color .2s;
}}

.nav-item:hover,
.nav-item.active {{
    background: #304a76;
    color: white;
}}

.sidebar-footer {{
    margin-top: auto;
    border-top: 1px solid #344665;
    padding: 18px 8px 0;
    font-size: 12px;
    color: #b5c2d8;
}}

main {{
    flex: 1;
    min-width: 0;
    padding: 30px 38px;
}}

.topbar {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 18px;
    margin-bottom: 32px;
    flex-wrap: wrap;
}}

.eyebrow {{
    font-size: 11px;
    letter-spacing: 1.5px;
    color: #64748b;
    font-weight: 700;
}}

.account {{
    display: flex;
    align-items: center;
    gap: 12px;
}}

.avatar {{
    width: 42px;
    height: 42px;
    border-radius: 50%;
    background: #dce7ff;
    color: #2457d6;
    display: grid;
    place-items: center;
    font-weight: 800;
}}

.account-email {{
    font-size: 12px;
    color: #64748b;
    overflow-wrap: anywhere;
}}

h1 {{
    font-size: 30px;
    letter-spacing: -.7px;
    margin: 0 0 9px;
}}

.intro {{
    color: #68778d;
    margin: 0;
    line-height: 1.7;
    font-size: 14px;
}}

.stats {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px;
    margin-top: 25px;
}}

.stat-card {{
    background: white;
    border: 1px solid #e3e9f2;
    border-radius: 14px;
    padding: 21px;
    min-width: 0;
    transition: transform .2s, box-shadow .2s;
}}

.stat-card:hover {{
    transform: translateY(-3px);
    box-shadow: 0 8px 24px #1720330d;
}}

.stat-label {{
    font-size: 12px;
    color: #64748b;
    font-weight: 700;
}}

.stat-value {{
    font-size: 32px;
    font-weight: 800;
    letter-spacing: -.5px;
    margin: 12px 0 6px;
    color: #18243a;
}}

.stat-note {{
    font-size: 11px;
    color: #8793a6;
    line-height: 1.5;
    overflow-wrap: anywhere;
}}

.banner {{
    margin-top: 27px;
    padding: 22px;
    background: #eaf0ff;
    border: 1px solid #d8e3ff;
    border-radius: 14px;
    display: flex;
    align-items: flex-start;
    gap: 15px;
}}

.banner-icon {{
    background: #d5e2ff;
    color: #2457d6;
    border-radius: 10px;
    padding: 11px 14px;
    font-weight: 800;
    flex-shrink: 0;
}}

.banner h2 {{
    font-size: 16px;
    margin: 0 0 8px;
}}

.banner p {{
    font-size: 13px;
    color: #526581;
    line-height: 1.7;
    margin: 0;
}}

.section-head {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    margin: 32px 0 17px;
    flex-wrap: wrap;
}}

.section-head h2 {{
    font-size: 19px;
    margin: 0;
}}

.section-head p {{
    font-size: 12px;
    color: #77859a;
    margin: 6px 0 0;
}}

.quick-actions {{
    display: flex;
    flex-wrap: wrap;
    gap: 11px;
    margin: 20px 0 28px;
}}

.quick-action {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    text-decoration: none;
    background: white;
    color: #2457d6;
    border: 1px solid #d8e2f3;
    padding: 11px 15px;
    border-radius: 9px;
    font-size: 12px;
    font-weight: 700;
    transition: .2s;
}}

.quick-action:hover {{
    background: #edf2ff;
    border-color: #9bb5ff;
}}

.quick-action.primary {{
    background: #2457d6;
    color: white;
    border-color: #2457d6;
}}

.quick-action.primary:hover {{
    background: #1945b5;
}}

.modules {{
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 17px;
}}

.module {{
    background: white;
    border: 1px solid #e3e9f2;
    border-radius: 14px;
    padding: 23px;
    display: flex;
    align-items: flex-start;
    gap: 15px;
    text-decoration: none;
    color: inherit;
    transition: transform .2s, border-color .2s, box-shadow .2s;
    min-width: 0;
}}

.module-link:hover {{
    transform: translateY(-3px);
    border-color: #9bb5ff;
    box-shadow: 0 8px 24px #1720330d;
}}

.module-icon {{
    width: 43px;
    height: 43px;
    border-radius: 11px;
    background: #edf2ff;
    color: #315dd0;
    display: grid;
    place-items: center;
    font-weight: 800;
    font-size: 12px;
    flex-shrink: 0;
}}

.module-content {{
    min-width: 0;
}}

.module h3 {{
    font-size: 14px;
    margin: 2px 0 8px;
}}

.module p {{
    font-size: 12px;
    color: #718096;
    line-height: 1.6;
    margin: 0 0 14px;
}}

.status {{
    font-size: 10px;
    color: #8b641c;
    background: #fff4d8;
    padding: 7px 9px;
    border-radius: 6px;
    display: inline-block;
}}

.status-ready {{
    color: #176b45;
    background: #dcfce7;
}}

.bottom {{
    margin-top: 28px;
    padding: 19px;
    background: white;
    border: 1px solid #e3e9f2;
    border-radius: 13px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 15px;
    flex-wrap: wrap;
}}

.bottom p {{
    font-size: 12px;
    color: #68778d;
    margin: 5px 0 0;
    overflow-wrap: anywhere;
}}

.logout {{
    border: 1px solid #d6deeb;
    background: white;
    color: #33435d;
    padding: 10px 16px;
    border-radius: 8px;
    cursor: pointer;
    font-weight: 650;
}}

.logout:hover {{
    background: #f2f5fa;
}}

@media (max-width: 1000px) {{
    main {{
        padding: 25px 22px;
    }}

    .sidebar {{
        width: 215px;
    }}

    .stats {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
}}

@media (max-width: 700px) {{
    .layout {{
        display: block;
    }}

    .sidebar {{
        width: 100%;
        padding: 15px 18px;
    }}

    .brand {{
        padding-bottom: 15px;
    }}

    .sidebar .nav-label {{
        display: none;
    }}

    .sidebar nav {{
        flex-direction: row;
        gap: 6px;
        overflow-x: auto;
        padding-bottom: 7px;
    }}

    .nav-item {{
        white-space: nowrap;
        margin: 0;
        flex-shrink: 0;
    }}

    .sidebar-footer {{
        display: none;
    }}

    main {{
        padding: 23px 16px;
    }}

    .modules {{
        grid-template-columns: 1fr;
    }}

    h1 {{
        font-size: 25px;
    }}
}}

@media (max-width: 420px) {{
    .stats {{
        grid-template-columns: 1fr;
    }}

    .banner {{
        padding: 16px;
    }}

    .quick-actions {{
        flex-direction: column;
    }}

    .quick-action {{
        width: 100%;
    }}

    .topbar {{
        align-items: flex-start;
    }}
}}
</style>
</head>

<body>

<div class="layout">

<aside class="sidebar">

    <div class="brand">
        <div class="logo">TP</div>
        <div>
            <div class="brand-name">T&amp;P Connect</div>
            <div class="brand-sub">PLACEMENT PORTAL</div>
        </div>
    </div>

    <div class="nav-label">WORKSPACE</div>

    <nav>
        <a class="nav-item active" href="/dashboard">Overview</a>
        {admin_sidebar_links}
    </nav>

    <div class="sidebar-footer">
        Placement operations made clearer.
    </div>

</aside>

<main>

<header class="topbar">

    <div class="eyebrow">WORKSPACE / OVERVIEW</div>

    <div class="account">
        <div>
            <div style="font-size:13px;font-weight:700">
                {safe_role}
            </div>
            <div class="account-email">{safe_email}</div>
        </div>

        <div class="avatar">TP</div>
    </div>

</header>

<section>
    <h1>{safe_heading}</h1>
    <p class="intro">{safe_description}</p>
</section>

{stats_html}

<section class="banner">

    <div class="banner-icon">i</div>

    <div>
        <h2>{safe_banner_title}</h2>
        <p>{safe_banner_description}</p>
    </div>

</section>

<div class="section-head">

    <div>
        <h2>{safe_section_title}</h2>
        <p>{safe_section_description}</p>
    </div>

</div>

<section class="quick-actions">
    {quick_actions_html}
</section>

<section class="modules">
    {module_cards}
</section>

<section class="bottom">

    <div>
        <strong style="font-size:13px">Your account</strong>
        <p>Signed in as {safe_email}</p>
    </div>

    <form method="post" action="/logout">

        <input
            type="hidden"
            name="csrf_token"
            value="{safe_csrf}"
        >

        <button class="logout" type="submit">
            Log out
        </button>

    </form>

</section>

</main>
</div>

</body>
</html>""")


# ---------------------------------------------------------
# LOGOUT
# ---------------------------------------------------------

@router.post("/logout")
def logout(
    request: Request,
    csrf_token: str = Form(..., max_length=100),
    db: Session = Depends(get_db),
):

    current = find_session(
        db, request.cookies.get(SESSION_COOKIE)
    )

    if current is None or not hmac.compare_digest(
        current.csrf_token, csrf_token
    ):
        return HTMLResponse(
            "Invalid or expired session.",
            status_code=403
        )

    db.delete(current)
    db.commit()

    response = RedirectResponse("/", status_code=303)

    response.delete_cookie(
        SESSION_COOKIE,
        path="/"
    )

    return response
