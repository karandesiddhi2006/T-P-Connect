import html
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, Student, Application, PlacementDrive, RecruitmentRound, ApplicationRoundResult
from app.security import SESSION_COOKIE, find_session

router = APIRouter()
def e(v): return html.escape(str(v if v is not None else ""), quote=True)
def auth(request, db):
    s=find_session(db, request.cookies.get(SESSION_COOKIE))
    if not s or not s.user_id: return None,None,RedirectResponse('/student/login',status_code=303)
    u=db.get(User,s.user_id)
    if not u or not u.is_active: return None,None,RedirectResponse('/student/login',status_code=303)
    if u.role!='student': return None,None,HTMLResponse('Student access required.',status_code=403)
    st=db.scalar(select(Student).where(Student.email==u.email))
    if not st or not st.is_active: return None,None,HTMLResponse('Active student record not found.',status_code=403)
    return s,st,None
def page(title, content):
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)} | T&P Connect</title><style>body{{font-family:Arial,sans-serif;background:#f4f6fa;color:#202b3c;margin:0;padding:24px}}main{{max-width:1100px;margin:auto}}.panel{{background:white;padding:22px;margin:18px 0;border-radius:12px;box-shadow:0 2px 10px #0000000a}}table{{width:100%;border-collapse:collapse}}th,td{{padding:11px;text-align:left;border-bottom:1px solid #e5e9f0;vertical-align:top}}th{{background:#f8fafc}}.wrap{{overflow-x:auto}}.muted{{color:#64748b}}a{{color:#234bc7}}.pill{{display:inline-block;padding:5px 9px;background:#eaf0ff;border-radius:15px}}</style></head><body><main><p><a href="/dashboard">Dashboard</a> · <a href="/student/profile">My Profile</a> · <a href="/student/applications">My Applications</a> · <a href="/drives">Placement Drives</a> · <a href="/notifications">Notifications</a></p>{content}</main></body></html>'''

@router.get('/student/profile', response_class=HTMLResponse)
def profile(request: Request, db: Session=Depends(get_db)):
    s,st,err=auth(request,db)
    if err:return err
    content=f'''<h1>My Profile</h1><section class="panel"><h2>{e(st.full_name)}</h2><table><tr><th>Roll Number</th><td>{e(st.roll_number)}</td></tr><tr><th>Email</th><td>{e(st.email)}</td></tr><tr><th>Branch</th><td>{e(st.branch)}</td></tr><tr><th>Graduation Year</th><td>{st.graduation_year}</td></tr><tr><th>CGPA</th><td>{st.cgpa:.2f}</td></tr><tr><th>Active Backlogs</th><td>{st.active_backlogs}</td></tr><tr><th>Total Backlogs</th><td>{st.total_backlogs}</td></tr><tr><th>Record Status</th><td>{'Active' if st.is_active else 'Inactive'}</td></tr></table><p class="muted">To correct academic information, contact the Training & Placement administrator.</p></section>'''
    return HTMLResponse(page('My Profile',content))

@router.get('/student/applications', response_class=HTMLResponse)
def my_applications(request: Request, db: Session=Depends(get_db)):
    s,st,err=auth(request,db)
    if err:return err
    apps=db.scalars(select(Application).where(Application.student_id==st.id).order_by(Application.applied_at.desc())).all()
    blocks=''
    for a in apps:
        d=db.get(PlacementDrive,a.drive_id)
        if not d: continue
        rounds=db.scalars(select(RecruitmentRound).where(RecruitmentRound.drive_id==d.id).order_by(RecruitmentRound.round_number)).all()
        trs=''
        for r in rounds:
            result=db.scalar(select(ApplicationRoundResult).where(ApplicationRoundResult.application_id==a.id,ApplicationRoundResult.round_id==r.id))
            outcome=result.result.title() if result else 'Pending'
            score=e(result.score) if result and result.score is not None else '—'
            remarks=e(result.remarks) if result and result.remarks else '—'
            scheduled=r.scheduled_at.strftime('%d %b %Y, %I:%M %p') if r.scheduled_at else 'Not scheduled'
            trs+=f'<tr><td>{r.round_number}</td><td>{e(r.name)}</td><td>{e(scheduled)}</td><td>{e(outcome)}</td><td>{score}</td><td>{remarks}</td></tr>'
        if not trs: trs='<tr><td colspan="6">Recruitment rounds have not been announced yet.</td></tr>'
        blocks+=f'''<section class="panel"><h2>{e(d.company_name)} — {e(d.job_role)}</h2><p>Applied: {e(a.applied_at.strftime('%d %b %Y'))} · Status: <span class="pill">{e(a.status.title())}</span></p><h3>Recruitment progress</h3><div class="wrap"><table><thead><tr><th>No.</th><th>Round</th><th>Schedule</th><th>Result</th><th>Score</th><th>Remarks</th></tr></thead><tbody>{trs}</tbody></table></div></section>'''
    if not blocks: blocks='<section class="panel">You have not applied to any placement drives yet. <a href="/drives">Browse published drives</a>.</section>'
    return HTMLResponse(page('My Applications',f'<h1>My Applications</h1>{blocks}'))
