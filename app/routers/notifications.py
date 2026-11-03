
import html
import hmac
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Notification, Student, User
from app.security import SESSION_COOKIE, find_session

router = APIRouter()

def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)

def page(title, content):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{esc(title)} | T&amp;P Connect</title>
    <style>
    body{{font-family:Arial,sans-serif;background:#f4f6fa;color:#202b3c;padding:24px}}
    main{{max-width:1000px;margin:auto}} .panel{{background:white;padding:22px;margin:18px 0;border-radius:12px}}
    input,select,textarea{{box-sizing:border-box;padding:10px;margin:5px 0 12px;width:100%;border:1px solid #ccd3df;border-radius:6px}}
    label{{display:block;font-weight:bold}} button{{background:#234bc7;color:white;border:0;border-radius:6px;padding:10px 13px;cursor:pointer}}
    .muted{{color:#64748b}} .unread{{border-left:4px solid #234bc7}} table{{width:100%;border-collapse:collapse}}
    th,td{{padding:9px;text-align:left;border-bottom:1px solid #e5e9f0}}
    </style></head><body><main><p><a href="/dashboard">Dashboard</a> ·
    <a href="/notifications">My Notifications</a> · <a href="/notifications/admin">Admin Notifications</a></p>
    {content}</main></body></html>"""

def current_user(request, db):
    session = find_session(db, request.cookies.get(SESSION_COOKIE))
    if not session or not session.user_id:
        return None, None, RedirectResponse("/login", status_code=303)
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None, None, RedirectResponse("/login", status_code=303)
    return session, user, None

def csrf_ok(session, token):
    return bool(token and hmac.compare_digest(session.csrf_token, token))

@router.get("/notifications", response_class=HTMLResponse)
def student_notifications(request: Request, db: Session = Depends(get_db)):
    session, user, error = current_user(request, db)
    if error: return error
    if user.role != "student": return HTMLResponse("Student access required.", status_code=403)
    student = db.scalar(select(Student).where(Student.email == user.email))
    if student is None:
        return HTMLResponse("Student login email does not match a student record. Contact the T&P administrator.", status_code=404)
    items = db.scalars(select(Notification).where(Notification.student_id == student.id).order_by(Notification.created_at.desc(), Notification.id.desc())).all()
    cards = ""
    for item in items:
        action = ""
        if not item.is_read:
            action = f"""<form method="post" action="/notifications/{item.id}/read">
            <input type="hidden" name="csrf_token" value="{esc(session.csrf_token)}">
            <button type="submit">Mark as read</button></form>"""
        safe_message = esc(item.message).replace("\\n", "<br>")
        cards += f"""<section class="panel {'unread' if not item.is_read else ''}">
        <p class="muted">{esc(item.category.title())} · {esc(item.created_at.strftime('%d %b %Y, %I:%M %p'))} · {'Read' if item.is_read else 'Unread'}</p>
        <h2>{esc(item.title)}</h2><p>{safe_message}</p>{action}</section>"""
    if not cards: cards = '<section class="panel">No notifications yet.</section>'
    return HTMLResponse(page("My Notifications", f"<h1>My Notifications</h1>{cards}"))

@router.post("/notifications/{notification_id}/read")
def mark_read(notification_id: int, request: Request, csrf_token: str = Form(..., max_length=100), db: Session = Depends(get_db)):
    session, user, error = current_user(request, db)
    if error: return error
    if user.role != "student": return HTMLResponse("Student access required.", status_code=403)
    if not csrf_ok(session, csrf_token): return HTMLResponse("Form expired. Reload and try again.", status_code=403)
    student = db.scalar(select(Student).where(Student.email == user.email))
    item = db.get(Notification, notification_id)
    if student is None or item is None or item.student_id != student.id:
        return HTMLResponse("Notification not found.", status_code=404)
    item.is_read = True
    try: db.commit()
    except SQLAlchemyError:
        db.rollback()
        return HTMLResponse("Could not update notification.", status_code=500)
    return RedirectResponse("/notifications", status_code=303)

@router.get("/notifications/admin", response_class=HTMLResponse)
def admin_notifications(request: Request, db: Session = Depends(get_db)):
    session, user, error = current_user(request, db)
    if error: return error
    if user.role != "admin": return HTMLResponse("Admin access required.", status_code=403)
    students = db.scalars(select(Student).where(Student.is_active.is_(True)).order_by(Student.roll_number)).all()
    recent = db.scalars(select(Notification).order_by(Notification.created_at.desc()).limit(30)).all()
    options = "".join(f'<option value="{s.id}">{esc(s.roll_number)} — {esc(s.full_name)}</option>' for s in students)
    rows = ""
    for n in recent:
        student = db.get(Student, n.student_id)
        rows += f"<tr><td>{esc(student.roll_number if student else '—')}</td><td>{esc(n.title)}</td><td>{'Read' if n.is_read else 'Unread'}</td><td>{esc(n.created_at.strftime('%d %b %Y'))}</td></tr>"
    if not rows: rows = '<tr><td colspan="4">No notifications sent yet.</td></tr>'
    content = f"""<h1>Student Notifications</h1><section class="panel"><h2>Create notification</h2>
    <form method="post" action="/notifications/admin/create">
    <input type="hidden" name="csrf_token" value="{esc(session.csrf_token)}">
    <label>Title *</label><input name="title" maxlength="160" required>
    <label>Message *</label><textarea name="message" rows="5" maxlength="5000" required></textarea>
    <label>Category</label><select name="category"><option value="general">General</option><option value="placement">Placement</option><option value="interview">Interview</option><option value="deadline">Deadline</option></select>
    <label>Recipient</label><select name="recipient"><option value="all">All active students</option>{options}</select>
    <button type="submit">Send notification</button></form></section>
    <section class="panel"><h2>Recently sent (latest 30)</h2><table><thead><tr><th>Roll No.</th><th>Title</th><th>Status</th><th>Created</th></tr></thead><tbody>{rows}</tbody></table></section>"""
    return HTMLResponse(page("Admin Notifications", content))

@router.post("/notifications/admin/create")
def create_notification(request: Request, title: str = Form(..., max_length=160), message: str = Form(..., max_length=5000), category: str = Form("general"), recipient: str = Form("all"), csrf_token: str = Form(..., max_length=100), db: Session = Depends(get_db)):
    session, user, error = current_user(request, db)
    if error: return error
    if user.role != "admin": return HTMLResponse("Admin access required.", status_code=403)
    if not csrf_ok(session, csrf_token): return HTMLResponse("Form expired. Reload and try again.", status_code=403)
    title, message = title.strip(), message.strip()
    if not title or not message: return HTMLResponse("Title and message are required.", status_code=400)
    if category not in {"general", "placement", "interview", "deadline"}: return HTMLResponse("Invalid category.", status_code=400)
    if recipient == "all":
        targets = db.scalars(select(Student).where(Student.is_active.is_(True))).all()
    else:
        try: target = db.get(Student, int(recipient))
        except ValueError: return HTMLResponse("Invalid recipient.", status_code=400)
        if target is None or not target.is_active: return HTMLResponse("Active student not found.", status_code=404)
        targets = [target]
    if not targets: return HTMLResponse("No active students found.", status_code=400)
    try:
        for student in targets:
            db.add(Notification(student_id=student.id, title=title, message=message, category=category, is_read=False))
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return HTMLResponse("Could not send notification.", status_code=500)
    return RedirectResponse("/notifications/admin", status_code=303)
