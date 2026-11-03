
import html
import hmac
import math
import re
from datetime import date
from io import BytesIO

import pymupdf
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PlacementDrive, User
from app.security import SESSION_COOKIE, find_session

router = APIRouter()

MAX_PDF_BYTES = 5 * 1024 * 1024
MAX_PDF_PAGES = 30


def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def get_admin(request: Request, db: Session):
    session = find_session(db, request.cookies.get(SESSION_COOKIE))

    if session is None or session.user_id is None:
        return None, RedirectResponse("/login", status_code=303)

    user = db.get(User, session.user_id)

    if user is None or not user.is_active:
        return None, RedirectResponse("/login", status_code=303)

    if user.role != "admin":
        return None, HTMLResponse("Admin access required.", status_code=403)

    return (session, user), None


def page(content: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JD PDF Analyzer | T&amp;P Connect</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#f4f7fb;color:#18243a;font-family:Segoe UI,Arial,sans-serif}}
header{{background:#172747;color:white;padding:18px 5%}}
header a{{color:#dce7ff;margin-right:16px;text-decoration:none}}
main{{max-width:950px;margin:28px auto;padding:0 18px}}
.panel{{background:white;border:1px solid #e1e8f1;border-radius:12px;padding:22px;margin:18px 0}}
label{{display:block;font-weight:600;font-size:14px;margin:12px 0 6px}}
input,textarea{{width:100%;padding:10px;border:1px solid #cbd5e1;border-radius:7px}}
button,.button{{display:inline-block;background:#2457d6;color:white;padding:11px 15px;border:0;border-radius:7px;text-decoration:none;cursor:pointer;margin-top:14px}}
.muted{{color:#64748b;font-size:14px}}
.notice{{background:#fff7df;border:1px solid #f2d58a;padding:13px;border-radius:8px}}
textarea{{min-height:90px}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f8fafc;padding:14px;border-radius:8px;max-height:300px;overflow:auto}}
table{{width:100%;border-collapse:collapse;margin-top:16px}}
th,td{{text-align:left;padding:10px;border-bottom:1px solid #e1e8f1}}
@media(max-width:650px){{.two{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<header><strong>T&amp;P Connect</strong>&nbsp;&nbsp;
<a href="/dashboard">Dashboard</a>
<a href="/drives">Placement Drives</a>
<a href="/eligibility">Eligibility Checker</a>
</header>
<main>{content}</main>
</body>
</html>"""


def extract_requirements(text: str) -> dict:
    """Extract common JD details conservatively; never invent eligibility rules."""
    result = {
        "company_name": "", "job_role": "", "package_lpa": "",
        "minimum_cgpa": "", "eligible_branches": "", "graduation_year": "",
        "maximum_active_backlogs": "", "maximum_total_backlogs": "", "notes": "",
    }

    clean = text.replace("\u00a0", " ").replace("\u2011", "-")
    lines = [re.sub(r"\s+", " ", x).strip(" \t•*-–") for x in clean.splitlines()]
    lines = [x for x in lines if x]
    joined = "\n".join(lines)

    # Role: support labelled roles and heading-style JDs such as
    # "JOB DESCRIPTION - SOFTWARE ENGINEER TRAINEE".
    for line in lines:
        m = re.search(r"(?i)\b(?:job\s*role|role|position|designation|profile)\s*[:\-]\s*(.{2,150})", line)
        if m:
            result["job_role"] = m.group(1).strip(" .;,")
            break
    if not result["job_role"]:
        for index, line in enumerate(lines[:8]):
            candidate = re.sub(r"(?i)^job\s+description\s*[:\-]?\s*", "", line).strip(" -–:")
            candidate = re.sub(r"(?i)\s*[-–:]\s*(?:job\s+description|job\s+profile|jd)\s*$", "", candidate).strip()
            if (candidate and len(candidate) <= 100 and
                re.search(r"(?i)\b(?:engineer|developer|analyst|trainee|intern|manager|consultant|designer|tester)\b", candidate)):
                if (index + 1 < min(len(lines), 8)
                    and len(lines[index + 1]) <= 40
                    and re.fullmatch(r"(?i)[A-Za-z][A-Za-z0-9 /&+.-]*", lines[index + 1])
                    and not re.search(r"(?i)\b(?:about|role|responsibilities|benefits|skills)\b", lines[index + 1])):
                    candidate += " " + lines[index + 1]
                result["job_role"] = candidate
                break

    # Company: explicit labels first, then common paragraph introductions.
    for line in lines:
        m = re.search(r"(?i)\b(?:company|organization|organisation)\s*(?:name)?\s*[:\-]\s*(.{2,150})", line)
        if m:
            result["company_name"] = m.group(1).strip(" .;,")
            break
    if not result["company_name"]:
        patterns = [
            r"(?i)\b([A-Z][A-Za-z0-9&.,'() -]{1,100}?(?:Pvt\.?\s*Ltd\.?|Private\s+Limited|Limited|Ltd\.?|LLP))\s+(?:specializes|specialises|is|provides|offers|was|has)\b",
            r"(?i)\b(?:about\s+the\s+company\s*[:\-]?\s*)([A-Z][A-Za-z0-9&.,'() -]{1,100}?(?:Pvt\.?\s*Ltd\.?|Private\s+Limited|Limited|Ltd\.?|LLP))\b",
            r"(?i)\b([A-Z][A-Za-z0-9&.,'() -]{1,100}?(?:Pvt\.?\s*Ltd\.?|Private\s+Limited|Limited|Ltd\.?|LLP))\s+(?:invites|is hiring|seeks|announces)\b",
        ]
        for pattern in patterns:
            m = re.search(pattern, clean)
            if m:
                result["company_name"] = re.sub(r"\s+", " ", m.group(1)).strip(" .;,")
                break

    # Package / compensation.
    m = re.search(r"(?i)\b(?:ctc|package|salary|compensation)\b[^\n]{0,80}?(\d+(?:\.\d+)?)\s*(?:lpa|lakhs?\s*(?:per annum|p\.?a\.?)?)", joined)
    if m:
        result["package_lpa"] = m.group(1)

    # Eligibility rules only when explicitly present.
    cgpa_patterns = [
        r"(?i)\b(?:minimum|min\.?)\s*(?:aggregate\s*)?(?:cgpa|c\.g\.p\.a\.|gpa)\s*(?:required)?\s*[:\-]?\s*(\d+(?:\.\d+)?)",
        r"(?i)\b(?:cgpa|c\.g\.p\.a\.|gpa)\s*(?:of|>=|at least|minimum|min\.?)?\s*[:\-]?\s*(\d+(?:\.\d+)?)",
    ]
    for pattern in cgpa_patterns:
        m = re.search(pattern, joined)
        if m and 0 <= float(m.group(1)) <= 10:
            result["minimum_cgpa"] = m.group(1)
            break

    for line in lines:
        m = re.search(r"(?i)\b(?:eligible branches|eligible streams|branches eligible|branches allowed)\s*[:\-]\s*(.{2,300})", line)
        if m:
            result["eligible_branches"] = m.group(1).strip(" .;")
            break
    m = re.search(r"(?i)\b(?:graduation year|passing year|batch|graduating batch|year of passing)\s*[:\-]?\s*(20\d{2})\b", joined)
    if m:
        result["graduation_year"] = m.group(1)

    m = re.search(r"(?i)\b(?:maximum|max\.?)\s*(?:number of\s*)?(?:active|live)\s*backlogs?\s*[:\-]?\s*(\d+)", joined)
    if not m:
        m = re.search(r"(?i)\b(?:active|live)\s*backlogs?\s*(?:allowed|permitted)?\s*[:\-]?\s*(\d+)", joined)
    if m:
        result["maximum_active_backlogs"] = m.group(1)
    elif re.search(r"(?i)\bno active backlogs\b|\bzero active backlogs\b", joined):
        result["maximum_active_backlogs"] = "0"

    m = re.search(r"(?i)\b(?:maximum|max\.?)\s*(?:number of\s*)?(?:total|history of|historical)\s*backlogs?\s*[:\-]?\s*(\d+)", joined)
    if not m:
        m = re.search(r"(?i)\b(?:total|historical)\s*backlogs?\s*(?:allowed|permitted)?\s*[:\-]?\s*(\d+)", joined)
    if m:
        result["maximum_total_backlogs"] = m.group(1)
    elif re.search(r"(?i)\bno history of backlogs\b|\bno past backlogs\b|\bno backlogs\b", joined):
        result["maximum_total_backlogs"] = "0"

    # Preserve useful JD sections as review notes. This is deliberately
    # text-based and conservative rather than pretending to understand every PDF layout.
    section_patterns = {
        "Company overview": r"(?is)(?:about\s+the\s+company)(.*?)(?=\n(?:role\s+overview|job\s+description|responsibilities|required\s+technical\s+skills|qualifications|eligibility|benefits)\b|\Z)",
        "Role overview": r"(?is)(?:role\s+overview)(.*?)(?=\n(?:responsibilities|required\s+technical\s+skills|qualifications|eligibility|benefits)\b|\Z)",
        "Responsibilities": r"(?is)(?:responsibilities|roles\s+and\s+responsibilities)(.*?)(?=\n(?:required\s+technical\s+skills|technical\s+skills|qualifications|eligibility|benefits)\b|\Z)",
        "Technical skills": r"(?is)(?:required\s+technical\s+skills|technical\s+skills|skills\s+required)(.*?)(?=\n(?:benefits|perks|eligibility|qualification|selection\s+process)\b|\Z)",
        "Benefits": r"(?is)(?:benefits|perks)(.*?)(?=\n(?:eligibility|how\s+to\s+apply|selection\s+process|application\s+process)\b|\Z)",
    }
    notes = []
    for label, pattern in section_patterns.items():
        m = re.search(pattern, joined)
        if m:
            value = re.sub(r"\s+", " ", m.group(1)).strip(" :-\n")
            if value:
                notes.append(f"{label}: {value[:1200]}")

    work_mode = re.search(r"(?i)\b(hybrid|remote|work\s+from\s+home|on[- ]site|onsite)\b", joined)
    if work_mode:
        notes.append("Work mode: " + work_mode.group(1))

    skills = re.search(r"(?i)(?:required\s+technical\s+skills|technical\s+skills|skills\s+required)\s*[:\-]?\s*([^\n]+(?:\n(?!\s*(?:benefits|eligibility)\b)[^\n]+)*)", joined)
    if skills and not any(x.startswith("Technical skills:") for x in notes):
        notes.append("Technical skills: " + re.sub(r"\s+", " ", skills.group(1)).strip()[:1200])

    result["notes"] = "Extracted JD details (verify against original):\n" + "\n".join(notes) if notes else ""
    return result

def normalize_duplicate_key(value: str) -> str:
    """Normalize text for a case-insensitive duplicate comparison."""
    return " ".join(value.casefold().split())


def find_possible_duplicates(
    db: Session,
    company_name: str,
    job_role: str,
    graduation_year: int,
):
    """
    Find drives matching company, job role and graduation year.

    Archived and draft drives are included to avoid overlooking earlier
    recruitment records. This is a warning, not proof of a duplicate.
    """
    company_key = normalize_duplicate_key(company_name)
    role_key = normalize_duplicate_key(job_role)

    existing_drives = db.scalars(select(PlacementDrive)).all()
    matches = []

    for drive in existing_drives:
        if (
            normalize_duplicate_key(drive.company_name) == company_key
            and normalize_duplicate_key(drive.job_role) == role_key
            and drive.graduation_year == graduation_year
        ):
            matches.append(drive)

    return matches


@router.get("/circular-analyzer", response_class=HTMLResponse)
def analyzer_home(request: Request, db: Session = Depends(get_db)):
    auth, error = get_admin(request, db)

    if error:
        return error

    content = f"""
<h1>Placement Circular / JD Analyzer</h1>
<p class="muted">Upload a text-based company PDF. The analyzer extracts common company, role,
skills and JD sections using rules. Verify every suggestion against the PDF.</p>
<div class="panel">
<div class="notice"><strong>Admin review required.</strong> Extracted values
are suggestions only. Confirm every criterion against the original PDF before
saving a drive. Missing or ambiguous values must be entered manually.</div>
<form method="post" action="/circular-analyzer/extract"
enctype="multipart/form-data">
<input type="hidden" name="csrf_token" value="{esc(auth[0].csrf_token)}">
<label for="pdf">Placement circular or Job Description
(PDF only, maximum 5 MB)</label>
<input id="pdf" name="pdf" type="file"
accept="application/pdf,.pdf" required>
<button type="submit">Upload and Extract</button>
</form>
</div>
"""

    return HTMLResponse(page(content))


@router.post("/circular-analyzer/extract", response_class=HTMLResponse)
async def extract_pdf(
    request: Request,
    pdf: UploadFile = File(...),
    csrf_token: str = Form(..., max_length=100),
    db: Session = Depends(get_db),
):
    auth, error = get_admin(request, db)

    if error:
        return error

    session, _user = auth

    if not hmac.compare_digest(session.csrf_token, csrf_token):
        await pdf.close()
        return HTMLResponse(
            page('<div class="panel"><h1>Form expired</h1>'
                 '<p>Reload the analyzer and submit the form again.</p>'
                 '<a class="button" href="/circular-analyzer">Return</a></div>'),
            status_code=403,
        )

    filename = pdf.filename or ""

    if (
        not filename.lower().endswith(".pdf")
        or pdf.content_type not in {
            "application/pdf",
            "application/octet-stream",
        }
    ):
        return HTMLResponse(
            page(
                '<div class="panel"><h1>Invalid file</h1>'
                '<p>Upload a PDF file only.</p>'
                '<a class="button" href="/circular-analyzer">Try again</a>'
                '</div>'
            ),
            status_code=400,
        )

    data = await pdf.read(MAX_PDF_BYTES + 1)
    await pdf.close()

    if not data or len(data) > MAX_PDF_BYTES:
        return HTMLResponse(
            page(
                '<div class="panel"><h1>File size error</h1>'
                '<p>Choose a non-empty PDF no larger than 5 MB.</p>'
                '<a class="button" href="/circular-analyzer">Try again</a>'
                '</div>'
            ),
            status_code=400,
        )

    try:
        with pymupdf.open(stream=BytesIO(data), filetype="pdf") as document:
            if document.is_encrypted:
                return HTMLResponse(
                    page(
                        '<div class="panel"><h1>Protected PDF</h1>'
                        '<p>Password-protected PDFs are not supported.</p>'
                        '<a class="button" href="/circular-analyzer">Try again</a>'
                        '</div>'
                    ),
                    status_code=400,
                )

            if document.page_count < 1 or document.page_count > MAX_PDF_PAGES:
                return HTMLResponse(
                    page(
                        '<div class="panel"><h1>Page limit</h1>'
                        '<p>PDF must contain between 1 and 30 pages.</p>'
                        '<a class="button" href="/circular-analyzer">Try again</a>'
                        '</div>'
                    ),
                    status_code=400,
                )

            extracted_text = "\n".join(
                pdf_page.get_text("text") for pdf_page in document
            )

    except Exception:
        return HTMLResponse(
            page(
                '<div class="panel"><h1>Could not read PDF</h1>'
                '<p>The file may be damaged or not a valid PDF. Try another file.</p>'
                '<a class="button" href="/circular-analyzer">Try again</a>'
                '</div>'
            ),
            status_code=400,
        )

    if not extracted_text.strip():
        return HTMLResponse(
            page(
                '<div class="panel"><h1>No selectable text found</h1>'
                '<p>This PDF may be scanned as images. OCR is not included yet. '
                'Use a text-based PDF or type the criteria manually in '
                'Placement Drives.</p>'
                '<a class="button" href="/drives">Open Placement Drives</a>'
                '</div>'
            ),
            status_code=400,
        )

    fields = extract_requirements(extracted_text)

    missing = [
        label
        for key, label in [
            ("company_name", "Company name"),
            ("job_role", "Job role"),
            ("minimum_cgpa", "Minimum CGPA"),
            ("eligible_branches", "Eligible branches"),
            ("graduation_year", "Graduation year"),
            ("maximum_active_backlogs", "Maximum active backlogs"),
            ("maximum_total_backlogs", "Maximum total backlogs"),
        ]
        if not fields[key]
    ]

    warning = (
        "Could not confidently extract: "
        + ", ".join(missing)
        + ". Check the original PDF and fill these fields."
        if missing
        else "Review every value against the original PDF before saving."
    )

    description_default = (
        "Extracted from: "
        + filename
        + "\n"
        + fields.get("notes", "")
        + "\n\nPlease verify all criteria against the original circular. "
        "Eligibility fields not stated in the PDF must be entered manually."
    ).strip()

    content = f"""
<h1>Review extracted requirements</h1>
<p class="muted">Source file: {esc(filename)}. The PDF is processed in memory
and is not saved to disk.</p>
<div class="notice"><strong>Important:</strong> {esc(warning)}
The extracted content is not automatically approved.</div>

<div class="panel">
<form method="post" action="/circular-analyzer/save">
<input type="hidden" name="csrf_token" value="{esc(session.csrf_token)}">

<div class="two">
<div>
<label for="company_name">Company name *</label>
<input id="company_name" name="company_name" maxlength="150" required
value="{esc(fields['company_name'])}">
</div>
<div>
<label for="job_role">Job role *</label>
<input id="job_role" name="job_role" maxlength="150" required
value="{esc(fields['job_role'])}">
</div>
<div>
<label for="package_lpa">Package (LPA, optional)</label>
<input id="package_lpa" name="package_lpa" type="number"
min="0" max="1000" step="0.01"
value="{esc(fields['package_lpa'])}">
</div>
<div>
<label for="minimum_cgpa">Minimum CGPA *</label>
<input id="minimum_cgpa" name="minimum_cgpa" type="number"
min="0" max="10" step="0.01" required
value="{esc(fields['minimum_cgpa'])}">
</div>
<div>
<label for="eligible_branches">Eligible branches * (comma-separated)</label>
<input id="eligible_branches" name="eligible_branches"
maxlength="500" required value="{esc(fields['eligible_branches'])}">
</div>
<div>
<label for="graduation_year">Graduation year *</label>
<input id="graduation_year" name="graduation_year" type="number"
min="2020" max="2100" required
value="{esc(fields['graduation_year'])}">
</div>
<div>
<label for="maximum_active_backlogs">Maximum active backlogs *</label>
<input id="maximum_active_backlogs" name="maximum_active_backlogs"
type="number" min="0" max="100" required
value="{esc(fields['maximum_active_backlogs'])}">
</div>
<div>
<label for="maximum_total_backlogs">Maximum total backlogs *</label>
<input id="maximum_total_backlogs" name="maximum_total_backlogs"
type="number" min="0" max="100" required
value="{esc(fields['maximum_total_backlogs'])}">
</div>
</div>

<label for="description">Notes / other requirements (optional)</label>
<textarea id="description" name="description"
maxlength="5000">{esc(description_default)}</textarea>

<p class="muted">This creates a draft drive. It does not notify students
or open applications.</p>

<label>
<input type="checkbox" name="review_confirmed" value="yes" required
style="width:auto">
I reviewed and corrected these values against the original PDF.
</label>

<button type="submit">Confirm Review and Save Draft Drive</button>
<a class="button" href="/circular-analyzer" style="background:#64748b">
Cancel
</a>
</form>
</div>

<div class="panel">
<h2>Extracted PDF text (preview)</h2>
<p class="muted">Use this preview to verify the suggested fields.</p>
<pre>{esc(extracted_text[:12000])}</pre>
</div>
"""

    return HTMLResponse(page(content))


@router.post("/circular-analyzer/save", response_class=HTMLResponse)
def save_reviewed_drive(
    request: Request,
    company_name: str = Form(..., max_length=150),
    job_role: str = Form(..., max_length=150),
    package_lpa: str = Form(""),
    minimum_cgpa: float = Form(...),
    eligible_branches: str = Form(..., max_length=500),
    graduation_year: int = Form(...),
    maximum_active_backlogs: int = Form(...),
    maximum_total_backlogs: int = Form(...),
    description: str = Form("", max_length=5000),
    review_confirmed: str = Form(""),
    allow_duplicate: str = Form(""),
    csrf_token: str = Form(..., max_length=100),
    db: Session = Depends(get_db),
):
    auth, error = get_admin(request, db)

    if error:
        return error

    session, user = auth

    if not hmac.compare_digest(session.csrf_token, csrf_token):
        return HTMLResponse(
            page(
                '<div class="panel"><h1>Form expired</h1>'
                '<p>Reload the analyzer and submit the form again.</p>'
                '<a class="button" href="/circular-analyzer">Return</a></div>'
            ),
            status_code=403,
        )

    if review_confirmed != "yes":
        return HTMLResponse(
            page(
                '<div class="panel"><h1>Review required</h1>'
                '<p>Please confirm that you reviewed the extracted requirements.</p>'
                '<a class="button" href="/circular-analyzer">Return</a></div>'
            ),
            status_code=400,
        )

    company_name = " ".join(company_name.split())
    job_role = " ".join(job_role.split())

    branches = list(
        dict.fromkeys(
            item.strip()
            for item in eligible_branches.split(",")
            if item.strip()
        )
    )

    if not company_name or not job_role or not branches:
        return HTMLResponse(
            page(
                '<div class="panel"><h1>Required fields missing</h1>'
                '<p>Company, role and eligible branches are required.</p>'
                '<a class="button" href="/circular-analyzer">Return</a></div>'
            ),
            status_code=400,
        )

    if not math.isfinite(minimum_cgpa) or not 0 <= minimum_cgpa <= 10:
        return HTMLResponse(
            page(
                '<div class="panel"><h1>Invalid CGPA</h1>'
                '<p>Minimum CGPA must be between 0 and 10.</p>'
                '<a class="button" href="/circular-analyzer">Return</a></div>'
            ),
            status_code=400,
        )

    if not 2020 <= graduation_year <= 2100:
        return HTMLResponse(
            page(
                '<div class="panel"><h1>Invalid graduation year</h1>'
                '<p>Graduation year must be between 2020 and 2100.</p>'
                '<a class="button" href="/circular-analyzer">Return</a></div>'
            ),
            status_code=400,
        )

    if not (
        0 <= maximum_active_backlogs
        <= maximum_total_backlogs
        <= 100
    ):
        return HTMLResponse(
            page(
                '<div class="panel"><h1>Invalid backlog limits</h1>'
                '<p>Limits must satisfy 0 &lt;= active &lt;= total &lt;= 100.</p>'
                '<a class="button" href="/circular-analyzer">Return</a></div>'
            ),
            status_code=400,
        )

    package = None

    if package_lpa.strip():
        try:
            package = float(package_lpa)
        except ValueError:
            return HTMLResponse(
                page(
                    '<div class="panel"><h1>Invalid package</h1>'
                    '<p>Package must be a valid number.</p>'
                    '<a class="button" href="/circular-analyzer">Return</a></div>'
                ),
                status_code=400,
            )

        if not math.isfinite(package) or not 0 <= package <= 1000:
            return HTMLResponse(
                page(
                    '<div class="panel"><h1>Invalid package</h1>'
                    '<p>Package must be between 0 and 1000 LPA.</p>'
                    '<a class="button" href="/circular-analyzer">Return</a></div>'
                ),
                status_code=400,
            )

    # Check for an existing drive with the same company, role and year.
    duplicates = find_possible_duplicates(
        db,
        company_name,
        job_role,
        graduation_year,
    )

    if duplicates and allow_duplicate != "yes":
        duplicate_rows = ""

        for drive in duplicates:
            duplicate_rows += f"""
            <tr>
                <td>{esc(drive.company_name)}</td>
                <td>{esc(drive.job_role)}</td>
                <td>{drive.graduation_year}</td>
                <td>{esc(drive.status)}</td>
            </tr>
            """

        hidden_fields = {
            "company_name": company_name,
            "job_role": job_role,
            "package_lpa": package_lpa,
            "minimum_cgpa": minimum_cgpa,
            "eligible_branches": ", ".join(branches),
            "graduation_year": graduation_year,
            "maximum_active_backlogs": maximum_active_backlogs,
            "maximum_total_backlogs": maximum_total_backlogs,
            "description": description,
            "review_confirmed": "yes",
            "csrf_token": csrf_token,
        }

        hidden_html = "".join(
            f'<input type="hidden" name="{esc(key)}" '
            f'value="{esc(value)}">'
            for key, value in hidden_fields.items()
        )

        content = f"""
<h1>Possible duplicate placement drive</h1>

<div class="panel">
<div class="notice">
<strong>Review before saving.</strong>
A drive with the same company, role and graduation year already exists.
It may be a duplicate, or it may represent a separate recruitment cycle.
</div>

<table>
<thead>
<tr>
<th>Company</th>
<th>Role</th>
<th>Graduation year</th>
<th>Status</th>
</tr>
</thead>
<tbody>{duplicate_rows}</tbody>
</table>

<p>What would you like to do?</p>

<form method="post" action="/circular-analyzer/save">
{hidden_html}
<input type="hidden" name="allow_duplicate" value="yes">
<button type="submit">This is intentional — Save New Draft</button>
</form>

<p>
<a class="button" href="/drives">Review Existing Drives</a>
<a class="button" href="/circular-analyzer" style="background:#64748b">
Cancel
</a>
</p>
</div>
"""

        return HTMLResponse(page(content), status_code=409)

    drive = PlacementDrive(
        company_name=company_name,
        job_role=job_role,
        package_lpa=package,
        minimum_cgpa=minimum_cgpa,
        eligible_branches=branches,
        graduation_year=graduation_year,
        maximum_active_backlogs=maximum_active_backlogs,
        maximum_total_backlogs=maximum_total_backlogs,
        application_deadline=None,
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

    return RedirectResponse(url="/drives", status_code=303)
