
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text

from app.database import engine
from app.routers.auth import router as auth_router
from app.routers.students import router as students_router
from app.routers.drives import router as drives_router
from app.routers.eligibility import router as eligibility_router
from app.routers.circular_analyzer import router as circular_analyzer_router
from app.routers.applications import router as applications_router
from app.routers.notifications import router as notifications_router
from app.routers.student_portal import router as student_portal_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    yield
    engine.dispose()


app = FastAPI(
    title="T&P Connect",
    description="Intelligent Placement Drive Management System",
    version="0.1.0",
    lifespan=lifespan,
)

# Register all existing routers.
app.include_router(auth_router)
app.include_router(students_router)
app.include_router(drives_router)
app.include_router(eligibility_router)
app.include_router(circular_analyzer_router)
app.include_router(applications_router)
app.include_router(notifications_router)
app.include_router(student_portal_router)


@app.get("/health")
def health_check():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return {
            "status": "healthy",
            "database": "connected",
        }

    except Exception:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "database": "unavailable",
            },
        )


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home():
    return HTMLResponse("""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>T&P Connect | Placement Portal</title>
<style>
* { box-sizing: border-box; }
body {
    margin: 0;
    min-height: 100vh;
    font-family: Inter, Segoe UI, Arial, sans-serif;
    background: #f3f6fc;
    color: #17243b;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
}
.container {
    width: 100%;
    max-width: 900px;
    text-align: center;
}
.logo {
    width: 58px;
    height: 58px;
    display: grid;
    place-items: center;
    margin: 0 auto 18px;
    background: #2457d6;
    color: white;
    border-radius: 15px;
    font-size: 22px;
    font-weight: 800;
}
h1 { font-size: 36px; margin: 0 0 10px; }
.subtitle {
    color: #64748b;
    line-height: 1.7;
    margin-bottom: 38px;
}
.cards {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 22px;
}
.card {
    background: white;
    padding: 34px 25px;
    border: 1px solid #e1e8f2;
    border-radius: 17px;
    text-decoration: none;
    color: inherit;
    transition: .2s;
}
.card:hover {
    transform: translateY(-4px);
    border-color: #9bb5ff;
    box-shadow: 0 12px 30px #17243b12;
}
.icon {
    font-size: 38px;
    margin-bottom: 15px;
}
h2 { font-size: 21px; margin: 0 0 10px; }
.card p {
    color: #718096;
    font-size: 13px;
    line-height: 1.7;
    min-height: 44px;
}
.btn {
    display: inline-block;
    margin-top: 15px;
    padding: 12px 23px;
    border-radius: 9px;
    color: white;
    font-size: 13px;
    font-weight: 700;
}
.admin .btn { background: #2457d6; }
.student .btn { background: #13845b; }
.footer {
    color: #94a3b8;
    font-size: 12px;
    margin-top: 35px;
}
@media(max-width:600px) {
    .cards { grid-template-columns: 1fr; }
    h1 { font-size: 29px; }
}
</style>
</head>
<body>
<div class="container">
    <div class="logo">TP</div>
    <h1>T&amp;P Connect</h1>
    <p class="subtitle">
        Intelligent Placement Drive Management System<br>
        Choose your account type to continue.
    </p>

    <div class="cards">
        <a class="card admin" href="/admin/login">
            <div class="icon">🛡️</div>
            <h2>Admin Portal</h2>
            <p>
                Manage student records, placement drives,
                eligibility, applications and notifications.
            </p>
            <span class="btn">Admin Login →</span>
        </a>

        <a class="card student" href="/student/login">
            <div class="icon">🎓</div>
            <h2>Student Portal</h2>
            <p>
                View placement opportunities, check eligibility,
                track applications and receive notifications.
            </p>
            <span class="btn">Student Login →</span>
        </a>
    </div>

    <div class="footer">
        T&amp;P Connect · Placement Management Portal
    </div>
</div>
</body>
</html>
""")


@app.get("/login", include_in_schema=False)
def legacy_login():
    return RedirectResponse("/admin/login", status_code=303)
