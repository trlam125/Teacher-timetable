from __future__ import annotations

import io
import json
import random
import secrets
import smtplib
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Optional
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, SignatureExpired, URLSafeSerializer, URLSafeTimedSerializer
import hashlib
import hmac
import os
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, func, inspect, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY")

if not DATABASE_URL:
    raise RuntimeError(
        "Thiếu DATABASE_URL. Hãy tạo file .env dựa trên .env.example "
        "và nhập chuỗi kết nối PostgreSQL."
    )
if not DATABASE_URL.startswith(("postgresql://", "postgresql+psycopg://")):
    raise RuntimeError("Project này chỉ hỗ trợ PostgreSQL.")
if not SECRET_KEY:
    raise RuntimeError(
        "Thiếu SECRET_KEY. Hãy tạo khóa bí mật và thêm vào file .env."
    )

# Chuẩn hóa về driver psycopg 3.
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://", "postgresql+psycopg://", 1
    )

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(120), default="Giáo viên")
    role: Mapped[str] = mapped_column(String(20), default="pending")
    requested_teacher_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    teacher_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    reset_token_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reset_token_expires_at: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    school_name: Mapped[str] = mapped_column(String(200), default="Trường học")
    days: Mapped[int] = mapped_column(Integer, default=6)
    sessions: Mapped[int] = mapped_column(Integer, default=2)
    periods_per_session: Mapped[int] = mapped_column(Integer, default=5)
    blocked_slots_json: Mapped[str] = mapped_column(Text, default="[]")
    share_token: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: secrets.token_urlsafe(16))
    created_at: Mapped[str] = mapped_column(String(40), default=lambda: datetime.now().isoformat(timespec="seconds"))

class Department(Base):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))

class Subject(Base):
    __tablename__ = "subjects"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    short_name: Mapped[str] = mapped_column(String(20))
    max_consecutive: Mapped[int] = mapped_column(Integer, default=1)

class Teacher(Base):
    __tablename__ = "teachers"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("departments.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    short_name: Mapped[str] = mapped_column(String(30))
    max_periods_day: Mapped[int] = mapped_column(Integer, default=5)
    unavailable_json: Mapped[str] = mapped_column(Text, default="[]")

class Grade(Base):
    __tablename__ = "grades"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))

class SchoolClass(Base):
    __tablename__ = "classes"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    grade_id: Mapped[Optional[int]] = mapped_column(ForeignKey("grades.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(80))
    unavailable_json: Mapped[str] = mapped_column(Text, default="[]")

class Assignment(Base):
    __tablename__ = "assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"))
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"))
    periods_per_week: Mapped[int] = mapped_column(Integer, default=1)
    consecutive_pattern: Mapped[str] = mapped_column(String(80), default="")

class FixedLesson(Base):
    __tablename__ = "fixed_lessons"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"))
    slot: Mapped[int] = mapped_column(Integer)

class Lesson(Base):
    __tablename__ = "lessons"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"))
    slot: Mapped[int] = mapped_column(Integer)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("project_id", "assignment_id", "slot", name="uq_lesson"),)

class TeacherPreference(Base):
    __tablename__ = "teacher_preferences"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), index=True)
    preferred_json: Mapped[str] = mapped_column(Text, default="[]")
    unavailable_json: Mapped[str] = mapped_column(Text, default="[]")
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    created_at: Mapped[str] = mapped_column(String(40), default=lambda: datetime.now().isoformat(timespec="seconds"))
    reviewed_at: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

Base.metadata.create_all(engine)

def migrate_schema():
    """Bổ sung các cột cũ còn thiếu bằng câu lệnh tương thích PostgreSQL."""
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("users")}
    role_was_added = "role" not in columns
    with engine.begin() as connection:
        if role_was_added:
            connection.exec_driver_sql(
                "ALTER TABLE users "
                "ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'pending'"
            )
        if "teacher_id" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN teacher_id INTEGER"
            )
        if "requested_teacher_name" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN requested_teacher_name VARCHAR(120)"
            )
        if "reset_token_hash" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN reset_token_hash VARCHAR(64)"
            )
        if "reset_token_expires_at" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN reset_token_expires_at VARCHAR(40)"
            )
        connection.exec_driver_sql(
            "UPDATE users SET role='pending' WHERE role IS NULL OR role='' OR role='user'"
        )
        if role_was_added and "projects" in inspector.get_table_names():
            # Legacy project owners were administrators before roles existed.
            connection.exec_driver_sql(
                "UPDATE users SET role='admin' "
                "WHERE id IN (SELECT DISTINCT owner_id FROM projects)"
            )
        connection.exec_driver_sql(
            "ALTER TABLE users ALTER COLUMN role SET DEFAULT 'pending'"
        )

        # Bản demo cũ từng được tạo chỉ với một buổi. Khôi phục cả sáng và chiều.
        if "projects" in inspector.get_table_names():
            project_columns = {column["name"] for column in inspector.get_columns("projects")}
            if "blocked_slots_json" not in project_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE projects ADD COLUMN blocked_slots_json TEXT NOT NULL DEFAULT '[]'"
                )
            connection.exec_driver_sql(
                "UPDATE projects SET sessions=2 "
                "WHERE name='TKB học kỳ I' AND school_name='THPT Demo' AND sessions=1"
            )

migrate_schema()
class Passwords:
    @staticmethod
    def hash(password: str) -> str:
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
        return f"pbkdf2_sha256${salt}${digest}"
    @staticmethod
    def verify(password: str, encoded: str) -> bool:
        try:
            algo, salt, digest = encoded.split("$", 2)
            if algo != "pbkdf2_sha256": return False
            actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
            return hmac.compare_digest(actual, digest)
        except Exception:
            return False
pwd = Passwords()
signer = URLSafeSerializer(SECRET_KEY, salt="session")
reset_signer = URLSafeTimedSerializer(SECRET_KEY, salt="password-reset")
captcha_signer = URLSafeTimedSerializer(SECRET_KEY, salt="forgot-password-captcha")

app = FastAPI(title="Teacher Timetable")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

DAYS = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]
RESET_TOKEN_TTL_SECONDS = 30 * 60
DEFAULT_ADMIN_EMAIL = "lam@gmail.com"
DEFAULT_ADMIN_PASSWORD = "admin123"
LEGACY_ADMIN_EMAILS = ("admin@gmail.com", "demo@school.vn")

def new_captcha() -> tuple[str, str]:
    left = secrets.randbelow(8) + 2
    right = secrets.randbelow(8) + 2
    token = captcha_signer.dumps({"answer": left + right})
    return f"{left} + {right} = ?", token

def captcha_is_valid(token: str, answer: str) -> bool:
    try:
        data = captcha_signer.loads(token, max_age=10 * 60)
        return hmac.compare_digest(str(data["answer"]), answer.strip())
    except (BadSignature, SignatureExpired, KeyError, ValueError):
        return False

def send_password_reset_email(recipient: str, reset_url: str) -> bool:
    smtp_host = os.getenv("SMTP_HOST")
    if not smtp_host:
        return False
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "no-reply@smart-tkb.local")
    use_ssl = os.getenv("SMTP_SSL", "false").lower() in {"1", "true", "yes"}

    message = EmailMessage()
    message["Subject"] = "Đặt lại mật khẩu Smart TKB"
    message["From"] = smtp_from
    message["To"] = recipient
    message.set_content(
        "Bạn vừa yêu cầu đặt lại mật khẩu Smart TKB.\n\n"
        f"Mở liên kết sau trong vòng 30 phút:\n{reset_url}\n\n"
        "Nếu bạn không yêu cầu, hãy bỏ qua email này."
    )

    smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with smtp_class(smtp_host, smtp_port, timeout=15) as client:
        if not use_ssl and os.getenv("SMTP_STARTTLS", "true").lower() in {"1", "true", "yes"}:
            client.starttls()
        if smtp_user:
            client.login(smtp_user, smtp_password)
        client.send_message(message)
    return True

def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def current_user(request: Request, db: Session = Depends(db_session)) -> User:
    raw = request.cookies.get("session")
    if not raw:
        raise HTTPException(401)
    try:
        data = signer.loads(raw)
    except BadSignature:
        raise HTTPException(401)
    user = db.get(User, int(data["uid"]))
    if not user:
        raise HTTPException(401)
    return user

def get_project(pid: int, user: User, db: Session) -> Project:
    if user.role != "admin":
        raise HTTPException(403,"Chỉ quản trị viên được thực hiện thao tác này")
    p = db.get(Project, pid)
    if not p or p.owner_id != user.id:
        raise HTTPException(404)
    return p

def slot_meta(project: Project, slot: int):
    ppd = project.sessions * project.periods_per_session
    day = slot // ppd
    inside = slot % ppd
    session = inside // project.periods_per_session
    period = inside % project.periods_per_session
    return day, session, period

def all_slots(project: Project):
    return list(range(project.days * project.sessions * project.periods_per_session))

def parse_slots(text: str):
    try:
        return set(int(x) for x in json.loads(text or "[]"))
    except Exception:
        return set()

def consecutive_groups(pattern:str,total_periods:int):
    text=(pattern or "").strip()
    if not text: return [1]*total_periods
    try:
        groups=[int(value.strip()) for value in text.split(",") if value.strip()]
    except ValueError as exc:
        raise ValueError("Mẫu tiết liên tiếp chỉ được chứa số nguyên, ví dụ 2,1,1.") from exc
    if not groups or any(value<1 for value in groups):
        raise ValueError("Mỗi cụm tiết liên tiếp phải lớn hơn 0.")
    if sum(groups)!=total_periods:
        raise ValueError(f"Tổng mẫu tiết phải bằng {total_periods} tiết/tuần.")
    return groups

def normalized_assignment_pattern(pattern:str,total_periods:int,subject:Subject):
    groups=consecutive_groups(pattern,total_periods)
    if any(value>subject.max_consecutive for value in groups):
        raise ValueError(f"Mỗi cụm không được vượt quá {subject.max_consecutive} tiết liên tiếp của môn {subject.name}.")
    return ",".join(str(value) for value in groups) if (pattern or "").strip() else ""

def valid_slots(project: Project, slots: list[int] | set[int]):
    maximum = project.days * project.sessions * project.periods_per_session
    return sorted({int(slot) for slot in slots if 0 <= int(slot) < maximum})

def bounded_int(value,default:int,minimum:int,maximum:int,label:str):
    raw=default if value in (None,"") else value
    if isinstance(raw,bool) or isinstance(raw,float) and not raw.is_integer():
        raise HTTPException(400,f"{label} phải là số nguyên từ {minimum} đến {maximum}")
    try:
        parsed=int(raw)
    except (TypeError,ValueError) as exc:
        raise HTTPException(400,f"{label} phải là số nguyên từ {minimum} đến {maximum}") from exc
    if not minimum<=parsed<=maximum:
        raise HTTPException(400,f"{label} phải nằm trong khoảng từ {minimum} đến {maximum}")
    return parsed

def pattern_slots_match(project:Project,pattern:str,total_periods:int,slots:list[int] | set[int]):
    """Kiểm tra các cụm tiết thực tế có đúng mẫu đã khai báo hay không."""
    if not (pattern or "").strip():
        return True
    try:
        expected=sorted(consecutive_groups(pattern,total_periods))
    except ValueError:
        return False
    if len(slots)!=total_periods:
        return False
    ppd=project.sessions*project.periods_per_session
    groups=defaultdict(list)
    for slot in sorted(set(slots)):
        day=slot//ppd
        inside=slot%ppd
        session=inside//project.periods_per_session
        period=inside%project.periods_per_session
        groups[(day,session)].append(period)
    actual=[]
    for periods in groups.values():
        run=1
        for left,right in zip(periods,periods[1:]):
            if right==left+1:
                run+=1
            else:
                actual.append(run);run=1
        actual.append(run)
    return sorted(actual)==expected

def assignment_pattern_matches(project:Project,assignment:Assignment,slots:list[int] | set[int]):
    return pattern_slots_match(
        project,
        assignment.consecutive_pattern,
        assignment.periods_per_week,
        slots,
    )

def accepted_teacher_preferences(db: Session, project_id: int):
    rows = db.scalars(
        select(TeacherPreference).where(
            TeacherPreference.project_id == project_id,
            TeacherPreference.status == "accepted",
        )
    ).all()
    preferred = defaultdict(set)
    unavailable = defaultdict(set)
    for row in rows:
        preferred[row.teacher_id].update(parse_slots(row.preferred_json))
        unavailable[row.teacher_id].update(parse_slots(row.unavailable_json))
    return preferred, unavailable

@app.exception_handler(401)
async def auth_error(request: Request, exc):
    return RedirectResponse("/login", 303)

@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(db_session)):
    raw = request.cookies.get("session")
    if raw:
        try:
            data=signer.loads(raw); user=db.get(User,int(data["uid"]))
            if user:
                destination = "/teacher" if user.role == "teacher" else ("/projects" if user.role == "admin" else "/account-pending")
                return RedirectResponse(destination, 303)
        except (BadSignature,KeyError,ValueError):
            pass
    return templates.TemplateResponse("landing.html", {"request": request})

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("auth.html", {"request": request, "mode": "login", "error": None})

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(db_session)):
    user = db.scalar(select(User).where(User.email == email.lower().strip()))
    if not user or not pwd.verify(password, user.password_hash):
        return templates.TemplateResponse("auth.html", {"request": request, "mode": "login", "error": "Email hoặc mật khẩu không đúng"}, status_code=400)
    destination = "/teacher" if user.role == "teacher" else ("/projects" if user.role == "admin" else "/account-pending")
    res = RedirectResponse(destination, 303)
    res.set_cookie("session", signer.dumps({"uid": user.id}), httponly=True, samesite="lax")
    return res

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("auth.html", {"request": request, "mode": "register", "error": None})

@app.post("/register")
def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    teacher_name: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(db_session),
):
    name = name.strip()
    email = email.lower().strip()
    teacher_name = teacher_name.strip()
    if not name:
        return templates.TemplateResponse("auth.html", {"request": request, "mode": "register", "error": "Họ tên tài khoản không được để trống"}, status_code=400)
    if not teacher_name:
        return templates.TemplateResponse("auth.html", {"request": request, "mode": "register", "error": "Tên giáo viên mong muốn không được để trống"}, status_code=400)
    if len(password) < 6:
        return templates.TemplateResponse("auth.html", {"request": request, "mode": "register", "error": "Mật khẩu phải có ít nhất 6 ký tự"}, status_code=400)
    if not email or "@" not in email:
        return templates.TemplateResponse("auth.html", {"request": request, "mode": "register", "error": "Email không hợp lệ"}, status_code=400)
    if db.scalar(select(User).where(User.email == email)):
        return templates.TemplateResponse("auth.html", {"request": request, "mode": "register", "error": "Email đã tồn tại"}, status_code=400)
    user = User(
        name=name,
        email=email,
        requested_teacher_name=teacher_name,
        password_hash=pwd.hash(password),
        role="pending",
    )
    db.add(user); db.commit()
    res = RedirectResponse("/account-pending", 303)
    res.set_cookie("session", signer.dumps({"uid": user.id}), httponly=True, samesite="lax")
    return res

@app.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request):
    question, captcha_token = new_captcha()
    return templates.TemplateResponse("forgot_password.html", {
        "request": request,
        "question": question,
        "captcha_token": captcha_token,
        "error": None,
        "submitted": False,
        "dev_reset_link": None,
    })

@app.post("/forgot-password", response_class=HTMLResponse)
def forgot_password(
    request: Request,
    email: str = Form(...),
    not_robot: Optional[str] = Form(None),
    captcha_answer: str = Form(...),
    captcha_token: str = Form(...),
    db: Session = Depends(db_session),
):
    if not_robot != "yes" or not captcha_is_valid(captcha_token, captcha_answer):
        question, fresh_token = new_captcha()
        return templates.TemplateResponse("forgot_password.html", {
            "request": request,
            "question": question,
            "captcha_token": fresh_token,
            "error": "Xác minh Tôi không phải robot chưa đúng. Vui lòng thử lại.",
            "submitted": False,
            "dev_reset_link": None,
        }, status_code=400)

    account = db.scalar(select(User).where(User.email == email.lower().strip()))
    dev_reset_link = None
    if account:
        nonce = secrets.token_urlsafe(32)
        account.reset_token_hash = hashlib.sha256(nonce.encode()).hexdigest()
        account.reset_token_expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=RESET_TOKEN_TTL_SECONDS)
        ).isoformat()
        db.commit()
        token = reset_signer.dumps({"uid": account.id, "nonce": nonce})
        reset_url = f"{str(request.base_url).rstrip('/')}/reset-password/{token}"
        try:
            email_sent = send_password_reset_email(account.email, reset_url)
        except (OSError, smtplib.SMTPException):
            email_sent = False
        if not email_sent and not os.getenv("SMTP_HOST"):
            dev_reset_link = reset_url

    question, fresh_token = new_captcha()
    return templates.TemplateResponse("forgot_password.html", {
        "request": request,
        "question": question,
        "captcha_token": fresh_token,
        "error": None,
        "submitted": True,
        "dev_reset_link": dev_reset_link,
    })

def reset_account_for_token(token: str, db: Session) -> Optional[User]:
    try:
        data = reset_signer.loads(token, max_age=RESET_TOKEN_TTL_SECONDS)
        account = db.get(User, int(data["uid"]))
        nonce_hash = hashlib.sha256(str(data["nonce"]).encode()).hexdigest()
        if not account or not account.reset_token_hash:
            return None
        if not hmac.compare_digest(account.reset_token_hash, nonce_hash):
            return None
        expires_at = datetime.fromisoformat(account.reset_token_expires_at or "")
        if expires_at < datetime.now(timezone.utc):
            return None
        return account
    except (BadSignature, SignatureExpired, KeyError, ValueError, TypeError):
        return None

@app.get("/reset-password/{token}", response_class=HTMLResponse)
def reset_password_page(token: str, request: Request, db: Session = Depends(db_session)):
    account = reset_account_for_token(token, db)
    return templates.TemplateResponse("reset_password.html", {
        "request": request,
        "token": token,
        "valid": account is not None,
        "error": None,
        "success": False,
    }, status_code=200 if account else 400)

@app.post("/reset-password/{token}", response_class=HTMLResponse)
def reset_password(
    token: str,
    request: Request,
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(db_session),
):
    account = reset_account_for_token(token, db)
    error = None
    if not account:
        error = "Liên kết đặt lại mật khẩu không hợp lệ, đã hết hạn hoặc đã được sử dụng."
    elif len(password) < 6:
        error = "Mật khẩu mới phải có ít nhất 6 ký tự."
    elif password != password_confirm:
        error = "Hai lần nhập mật khẩu không khớp."
    if error:
        return templates.TemplateResponse("reset_password.html", {
            "request": request,
            "token": token,
            "valid": account is not None,
            "error": error,
            "success": False,
        }, status_code=400)

    account.password_hash = pwd.hash(password)
    account.reset_token_hash = None
    account.reset_token_expires_at = None
    db.commit()
    return templates.TemplateResponse("reset_password.html", {
        "request": request,
        "token": token,
        "valid": False,
        "error": None,
        "success": True,
    })

@app.get("/logout")
def logout():
    res = RedirectResponse("/", 303); res.delete_cookie("session"); return res

@app.get("/account-pending", response_class=HTMLResponse)
def account_pending(request: Request, user: User = Depends(current_user)):
    if user.role == "admin":
        return RedirectResponse("/projects", 303)
    if user.role == "teacher":
        return RedirectResponse("/teacher", 303)
    return templates.TemplateResponse("user_pending.html", {"request": request, "user": user})

@app.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request, user: User = Depends(current_user), db: Session = Depends(db_session)):
    if user.role != "admin":
        raise HTTPException(403, "Chỉ quản trị viên được quản lý tài khoản")
    users = db.scalars(select(User).order_by(User.id.asc())).all()
    projects = db.scalars(select(Project).where(Project.owner_id == user.id)).all()
    project_names = {project.id: project.name for project in projects}
    project_ids = list(project_names)
    assigned_teacher_ids = set(db.scalars(
        select(User.teacher_id).where(User.role == "teacher", User.teacher_id.is_not(None))
    ).all())
    available_teachers = []
    managed_teacher_ids = set()
    if project_ids:
        teachers = db.scalars(
            select(Teacher).where(Teacher.project_id.in_(project_ids)).order_by(Teacher.name.asc())
        ).all()
        managed_teacher_ids = {teacher.id for teacher in teachers}
        available_teachers = [
            {
                "id": teacher.id,
                "name": teacher.name,
                "project_name": project_names[teacher.project_id],
            }
            for teacher in teachers
            if teacher.id not in assigned_teacher_ids
        ]
    return templates.TemplateResponse("users.html", {
        "request": request,
        "user": user,
        "users": users,
        "available_teachers": available_teachers,
        "managed_projects": projects,
        "managed_teacher_ids": managed_teacher_ids,
    })

@app.post("/admin/users/{account_id}/update")
def update_account(
    account_id: int,
    name: str = Form(...),
    email: str = Form(...),
    requested_teacher_name: str = Form(""),
    password: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if user.role != "admin":
        raise HTTPException(403, "Chỉ quản trị viên được quản lý tài khoản")
    account = db.get(User, account_id)
    if not account:
        raise HTTPException(404, "Không tìm thấy tài khoản")
    name = name.strip()
    email = email.lower().strip()
    if not name:
        raise HTTPException(400, "Họ tên không được để trống")
    if not email or "@" not in email:
        raise HTTPException(400, "Email không hợp lệ")
    conflict = db.scalar(select(User).where(User.email == email, User.id != account.id))
    if conflict:
        raise HTTPException(409, "Email đã được dùng cho tài khoản khác")
    account.name = name
    account.email = email
    account.requested_teacher_name = requested_teacher_name.strip() or None
    if password.strip():
        if len(password.strip()) < 6:
            raise HTTPException(400, "Mật khẩu mới phải có ít nhất 6 ký tự")
        account.password_hash = pwd.hash(password.strip())
    db.commit()
    return RedirectResponse("/admin/users", 303)

@app.post("/admin/users/{account_id}/delete")
def delete_account(
    account_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if user.role != "admin":
        raise HTTPException(403, "Chỉ quản trị viên được quản lý tài khoản")
    account = db.get(User, account_id)
    if not account:
        raise HTTPException(404, "Không tìm thấy tài khoản")
    if account.id == user.id:
        raise HTTPException(400, "Không thể xóa chính tài khoản đang đăng nhập")
    if db.scalar(select(Project.id).where(Project.owner_id == account.id)) is not None:
        raise HTTPException(400, "Không thể xóa tài khoản đang sở hữu bộ thời khóa biểu")
    db.delete(account)
    db.commit()
    return RedirectResponse("/admin/users", 303)

@app.post("/admin/users/{account_id}/approve")
def approve_teacher_account(
    account_id: int,
    teacher_id: str = Form(""),
    project_id: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if user.role != "admin":
        raise HTTPException(403, "Chỉ quản trị viên được quản lý tài khoản")
    account = db.get(User, account_id)
    if not account:
        raise HTTPException(404, "Không tìm thấy tài khoản")
    if account.role != "pending":
        raise HTTPException(400, "Chỉ có thể duyệt tài khoản đang chờ")
    teacher_id = teacher_id.strip()
    project_id = project_id.strip()
    if teacher_id and not teacher_id.isdigit():
        raise HTTPException(400, "Giáo viên được chọn không hợp lệ")
    if project_id and not project_id.isdigit():
        raise HTTPException(400, "Bộ thời khóa biểu được chọn không hợp lệ")
    selected_teacher_id = int(teacher_id) if teacher_id else None
    selected_project_id = int(project_id) if project_id else None
    if selected_teacher_id is not None:
        teacher = db.get(Teacher, selected_teacher_id)
        project = db.get(Project, teacher.project_id) if teacher else None
        if not teacher or not project or project.owner_id != user.id:
            raise HTTPException(400, "Giáo viên không hợp lệ hoặc không thuộc bộ thời khóa biểu của bạn")
        existing_account = db.scalar(
            select(User).where(User.role == "teacher", User.teacher_id == teacher.id)
        )
        if existing_account:
            raise HTTPException(400, "Giáo viên này đã có tài khoản")
    else:
        teacher_name = (account.requested_teacher_name or "").strip()
        if not teacher_name:
            raise HTTPException(400, "Hãy nhập tên giáo viên mong muốn hoặc chọn một giáo viên có sẵn")
        managed_projects = db.scalars(
            select(Project).where(Project.owner_id == user.id).order_by(Project.id.asc())
        ).all()
        if selected_project_id is None and len(managed_projects) == 1:
            project = managed_projects[0]
        else:
            project = db.get(Project, selected_project_id) if selected_project_id is not None else None
        if not project or project.owner_id != user.id:
            raise HTTPException(400, "Hãy chọn bộ thời khóa biểu để tạo hồ sơ giáo viên mới")
        short_name = teacher_name.split()[-1][:30]
        teacher = Teacher(
            project_id=project.id,
            name=teacher_name,
            short_name=short_name,
            max_periods_day=5,
        )
        db.add(teacher)
        db.flush()
    account.role = "teacher"
    account.teacher_id = teacher.id
    db.commit()
    return RedirectResponse("/admin/users", 303)

@app.post("/admin/users/{account_id}/promote-admin")
def promote_teacher_to_admin(
    account_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    if user.role != "admin":
        raise HTTPException(403, "Chỉ quản trị viên được quản lý tài khoản")
    account = db.get(User, account_id)
    if not account:
        raise HTTPException(404, "Không tìm thấy tài khoản")
    if account.role != "teacher":
        raise HTTPException(400, "Chỉ có thể nâng tài khoản giáo viên lên quản trị viên")
    teacher = db.get(Teacher, account.teacher_id) if account.teacher_id else None
    project = db.get(Project, teacher.project_id) if teacher else None
    if not teacher or not project or project.owner_id != user.id:
        raise HTTPException(403, "Bạn không quản lý tài khoản giáo viên này")
    account.role = "admin"
    account.teacher_id = None
    db.commit()
    return RedirectResponse("/admin/users", 303)

@app.get("/projects", response_class=HTMLResponse)
def projects(request: Request, user: User = Depends(current_user), db: Session = Depends(db_session)):
    if user.role == "teacher":
        return RedirectResponse("/teacher", 303)
    if user.role != "admin":
        return RedirectResponse("/account-pending", 303)
    rows = db.scalars(select(Project).where(Project.owner_id == user.id).order_by(Project.id.desc())).all()
    return templates.TemplateResponse("projects.html", {"request": request, "user": user, "projects": rows})

@app.post("/projects")
def create_project(name: str = Form(...), school_name: str = Form(...), days: int = Form(6), sessions: int = Form(2), periods: int = Form(5), user: User = Depends(current_user), db: Session = Depends(db_session)):
    if user.role!="admin": raise HTTPException(403)
    p = Project(owner_id=user.id, name=name, school_name=school_name, days=max(1,min(days,7)), sessions=max(1,min(sessions,2)), periods_per_session=max(1,min(periods,8)))
    db.add(p); db.commit(); seed_project(db, p)
    return RedirectResponse(f"/projects/{p.id}", 303)

@app.post("/projects/{pid}/clone")
def clone_project(pid: int, user: User = Depends(current_user), db: Session = Depends(db_session)):
    src = get_project(pid,user,db)
    p = Project(owner_id=user.id,name=src.name+" (bản sao)",school_name=src.school_name,days=src.days,sessions=src.sessions,periods_per_session=src.periods_per_session,blocked_slots_json=src.blocked_slots_json)
    db.add(p); db.flush()
    maps = {"dep":{},"sub":{},"tea":{},"grade":{},"cls":{},"ass":{}}
    for x in db.scalars(select(Department).where(Department.project_id==pid)):
        n=Department(project_id=p.id,name=x.name);db.add(n);db.flush();maps["dep"][x.id]=n.id
    for x in db.scalars(select(Subject).where(Subject.project_id==pid)):
        n=Subject(project_id=p.id,name=x.name,short_name=x.short_name,max_consecutive=x.max_consecutive);db.add(n);db.flush();maps["sub"][x.id]=n.id
    for x in db.scalars(select(Teacher).where(Teacher.project_id==pid)):
        n=Teacher(project_id=p.id,department_id=maps["dep"].get(x.department_id),name=x.name,short_name=x.short_name,max_periods_day=x.max_periods_day,unavailable_json=x.unavailable_json);db.add(n);db.flush();maps["tea"][x.id]=n.id
    for x in db.scalars(select(Grade).where(Grade.project_id==pid)):
        n=Grade(project_id=p.id,name=x.name);db.add(n);db.flush();maps["grade"][x.id]=n.id
    for x in db.scalars(select(SchoolClass).where(SchoolClass.project_id==pid)):
        n=SchoolClass(project_id=p.id,grade_id=maps["grade"].get(x.grade_id),name=x.name,unavailable_json=x.unavailable_json);db.add(n);db.flush();maps["cls"][x.id]=n.id
    for x in db.scalars(select(Assignment).where(Assignment.project_id==pid)):
        n=Assignment(project_id=p.id,class_id=maps["cls"][x.class_id],subject_id=maps["sub"][x.subject_id],teacher_id=maps["tea"][x.teacher_id],periods_per_week=x.periods_per_week,consecutive_pattern=x.consecutive_pattern);db.add(n);db.flush();maps["ass"][x.id]=n.id
    for x in db.scalars(select(FixedLesson).where(FixedLesson.project_id==pid)):
        if x.assignment_id in maps["ass"]:
            db.add(FixedLesson(project_id=p.id,assignment_id=maps["ass"][x.assignment_id],slot=x.slot))
    for x in db.scalars(select(Lesson).where(Lesson.project_id==pid)):
        db.add(Lesson(project_id=p.id,assignment_id=maps["ass"][x.assignment_id],slot=x.slot,locked=x.locked))
    db.commit(); return RedirectResponse(f"/projects/{p.id}",303)

@app.get("/projects/{pid}", response_class=HTMLResponse)
def project_page(pid:int, request:Request, user:User=Depends(current_user), db:Session=Depends(db_session)):
    p=get_project(pid,user,db)
    data=project_data(db,p)
    return templates.TemplateResponse("workspace.html", {"request":request,"user":user,"p":p,"data":data,"days":DAYS})

class EntityIn(BaseModel):
    type: str
    data: dict

@app.post("/api/projects/{pid}/entity")
def add_entity(pid:int, payload:EntityIn, user:User=Depends(current_user), db:Session=Depends(db_session)):
    p=get_project(pid,user,db); d=payload.data
    if payload.type=="department": obj=Department(project_id=pid,name=d["name"])
    elif payload.type=="subject":
        max_consecutive=bounded_int(d.get("max_consecutive"),1,1,4,"Số tiết liên tiếp tối đa")
        obj=Subject(project_id=pid,name=d["name"],short_name=d.get("short_name") or d["name"][:5],max_consecutive=max_consecutive)
    elif payload.type=="teacher":
        department_id=d.get("department_id") or None
        if department_id:
            department=db.get(Department,int(department_id))
            if not department or department.project_id!=pid: raise HTTPException(400,"Tổ chuyên môn không hợp lệ")
        max_periods_day=bounded_int(d.get("max_periods_day"),5,1,10,"Số tiết tối đa mỗi ngày")
        obj=Teacher(project_id=pid,name=d["name"],short_name=d.get("short_name") or d["name"],department_id=department_id,max_periods_day=max_periods_day,unavailable_json=json.dumps(d.get("unavailable",[])))
    elif payload.type=="grade": obj=Grade(project_id=pid,name=d["name"])
    elif payload.type=="class":
        grade_id=d.get("grade_id") or None
        if grade_id:
            grade=db.get(Grade,int(grade_id))
            if not grade or grade.project_id!=pid: raise HTTPException(400,"Khối lớp không hợp lệ")
        obj=SchoolClass(project_id=pid,name=d["name"],grade_id=grade_id,unavailable_json=json.dumps(d.get("unavailable",[])))
    elif payload.type=="assignment":
        school_class=db.get(SchoolClass,int(d["class_id"])); subject=db.get(Subject,int(d["subject_id"])); teacher=db.get(Teacher,int(d["teacher_id"]))
        if not school_class or not subject or not teacher or any(x.project_id!=pid for x in (school_class,subject,teacher)):
            raise HTTPException(400,"Lớp, môn hoặc giáo viên không thuộc bộ thời khóa biểu")
        duplicate=db.scalar(select(Assignment.id).where(
            Assignment.project_id==pid,
            Assignment.class_id==school_class.id,
            Assignment.subject_id==subject.id,
            Assignment.teacher_id==teacher.id,
        ))
        if duplicate is not None:
            raise HTTPException(409,"Phân công lớp – môn – giáo viên này đã tồn tại")
        periods=bounded_int(d.get("periods_per_week"),1,1,40,"Số tiết mỗi tuần")
        try: pattern=normalized_assignment_pattern(d.get("consecutive_pattern",""),periods,subject)
        except ValueError as exc: raise HTTPException(400,str(exc)) from exc
        obj=Assignment(project_id=pid,class_id=school_class.id,subject_id=subject.id,teacher_id=teacher.id,periods_per_week=periods,consecutive_pattern=pattern)
    else: raise HTTPException(400,"Loại dữ liệu không hợp lệ")
    db.add(obj); db.commit(); return {"ok":True,"id":obj.id}

@app.put("/api/projects/{pid}/entity/{typ}/{eid}")
def update_entity(
    pid: int,
    typ: str,
    eid: int,
    payload: EntityIn,
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    project = get_project(pid, user, db)
    if payload.type != typ or typ not in {"subject", "teacher", "class"}:
        raise HTTPException(400, "Loại dữ liệu không hợp lệ")
    model = {"subject": Subject, "teacher": Teacher, "class": SchoolClass}[typ]
    obj = db.get(model, eid)
    if not obj or obj.project_id != pid:
        raise HTTPException(404, "Không tìm thấy dữ liệu cần sửa")
    d = payload.data
    name = str(d.get("name", "")).strip()
    if not name:
        raise HTTPException(400, "Tên không được để trống")
    if typ == "subject":
        short_name = str(d.get("short_name", "")).strip()
        if not short_name:
            raise HTTPException(400, "Tên rút gọn không được để trống")
        try:
            new_max_consecutive = max(1, min(int(d.get("max_consecutive", 1)), 4))
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "Số tiết liên tiếp tối đa phải là số từ 1 đến 4") from exc
        assignments = db.scalars(select(Assignment).where(Assignment.subject_id == obj.id)).all()
        incompatible = []
        for assignment in assignments:
            if (assignment.consecutive_pattern or "").strip():
                try:
                    groups = consecutive_groups(assignment.consecutive_pattern, assignment.periods_per_week)
                except ValueError:
                    incompatible.append(assignment.id)
                    continue
                if any(group > new_max_consecutive for group in groups):
                    incompatible.append(assignment.id)
                    continue
            lesson_slots = db.scalars(select(Lesson.slot).where(Lesson.assignment_id == assignment.id)).all()
            periods_by_session = defaultdict(list)
            periods_per_day = project.sessions * project.periods_per_session
            for slot in lesson_slots:
                day = slot // periods_per_day
                inside_day = slot % periods_per_day
                session = inside_day // project.periods_per_session
                period = inside_day % project.periods_per_session
                periods_by_session[(day, session)].append(period)
            schedule_exceeds_limit = False
            for periods in periods_by_session.values():
                longest = run = 0
                previous = None
                for period in sorted(set(periods)):
                    run = run + 1 if previous is not None and period == previous + 1 else 1
                    longest = max(longest, run)
                    previous = period
                if longest > new_max_consecutive:
                    schedule_exceeds_limit = True
                    break
            if schedule_exceeds_limit:
                incompatible.append(assignment.id)
        if incompatible:
            raise HTTPException(
                409,
                f"Không thể giảm còn {new_max_consecutive} tiết liên tiếp vì có {len(incompatible)} phân công đang dùng cụm dài hơn. Hãy sửa cách chia tiết của các phân công đó trước.",
            )
        obj.name = name
        obj.short_name = short_name[:20]
        obj.max_consecutive = new_max_consecutive
    elif typ == "teacher":
        short_name = str(d.get("short_name", "")).strip()
        if not short_name:
            raise HTTPException(400, "Tên ngắn không được để trống")
        department_id = d.get("department_id") or None
        if department_id:
            department = db.get(Department, int(department_id))
            if not department or department.project_id != pid:
                raise HTTPException(400, "Tổ chuyên môn không hợp lệ")
        obj.name = name
        obj.short_name = short_name[:30]
        obj.department_id = department_id
        obj.max_periods_day = max(1, min(int(d.get("max_periods_day", 5)), 10))
    else:
        grade_id = d.get("grade_id") or None
        if grade_id:
            grade = db.get(Grade, int(grade_id))
            if not grade or grade.project_id != pid:
                raise HTTPException(400, "Khối lớp không hợp lệ")
        obj.name = name
        obj.grade_id = grade_id
    db.commit()
    return {"ok": True}

class AssignmentUpdateIn(BaseModel):
    periods_per_week: int
    consecutive_pattern: str = ""

@app.put("/api/projects/{pid}/assignments/{assignment_id}")
def update_assignment(pid:int,assignment_id:int,payload:AssignmentUpdateIn,user:User=Depends(current_user),db:Session=Depends(db_session)):
    project=get_project(pid,user,db)
    assignment=db.get(Assignment,assignment_id)
    if not assignment or assignment.project_id!=pid: raise HTTPException(404)
    periods=max(1,min(int(payload.periods_per_week),40))
    scheduled=db.scalar(select(func.count(Lesson.id)).where(Lesson.assignment_id==assignment.id)) or 0
    if periods<scheduled:
        return JSONResponse({"ok":False,"message":f"Đang có {scheduled} tiết trên lịch. Hãy gỡ bớt tiết trước khi giảm số tiết/tuần."},409)
    subject=db.get(Subject,assignment.subject_id)
    if not subject or subject.project_id!=pid: raise HTTPException(409,"Môn học của phân công không còn tồn tại")
    try: pattern=normalized_assignment_pattern(payload.consecutive_pattern,periods,subject)
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc
    if scheduled==periods:
        current_slots=db.scalars(select(Lesson.slot).where(Lesson.assignment_id==assignment.id)).all()
        if not pattern_slots_match(project,pattern,periods,current_slots):
            return JSONResponse({
                "ok":False,
                "message":"Lịch hiện tại chưa đúng cách chia tiết mới. Hãy đưa phân công này về khay hoặc sắp xếp lại các tiết trước khi lưu mẫu.",
            },409)
    assignment.periods_per_week=periods
    assignment.consecutive_pattern=pattern
    db.commit();return {"ok":True}

@app.delete("/api/projects/{pid}/entity/{typ}/{eid}")
def delete_entity(pid:int,typ:str,eid:int,user:User=Depends(current_user),db:Session=Depends(db_session)):
    get_project(pid,user,db)
    model={"department":Department,"subject":Subject,"teacher":Teacher,"grade":Grade,"class":SchoolClass,"assignment":Assignment}.get(typ)
    if not model: raise HTTPException(400)
    obj=db.get(model,eid)
    if not obj or obj.project_id!=pid: raise HTTPException(404)
    dependency={
        "department":db.scalar(select(Teacher.id).where(Teacher.department_id==eid)),
        "subject":db.scalar(select(Assignment.id).where(Assignment.subject_id==eid)),
        "teacher":db.scalar(select(Assignment.id).where(Assignment.teacher_id==eid)),
        "grade":db.scalar(select(SchoolClass.id).where(SchoolClass.grade_id==eid)),
        "class":db.scalar(select(Assignment.id).where(Assignment.class_id==eid)),
    }.get(typ)
    if dependency is not None:
        return JSONResponse({"ok":False,"message":"Không thể xóa vì dữ liệu đang được sử dụng."},409)
    if typ=="teacher" and db.scalar(select(User.id).where(User.role=="teacher",User.teacher_id==eid)) is not None:
        return JSONResponse({"ok":False,"message":"Hãy thu hồi tài khoản giáo viên trước khi xóa."},409)
    if typ=="assignment":
        for l in db.scalars(select(Lesson).where(Lesson.assignment_id==eid)).all(): db.delete(l)
        for fixed_lesson in db.scalars(select(FixedLesson).where(FixedLesson.assignment_id==eid)).all(): db.delete(fixed_lesson)
    if typ=="teacher":
        for preference in db.scalars(select(TeacherPreference).where(TeacherPreference.teacher_id==eid)).all():
            db.delete(preference)
    db.delete(obj); db.commit(); return {"ok":True}

class ConstraintIn(BaseModel):
    entity_type: str
    entity_id: int
    slots: list[int]

@app.post("/api/projects/{pid}/constraints")
def constraints(pid:int,payload:ConstraintIn,user:User=Depends(current_user),db:Session=Depends(db_session)):
    p=get_project(pid,user,db)
    if payload.entity_type not in {"teacher","class"}: raise HTTPException(400,"Loại ràng buộc không hợp lệ")
    model=Teacher if payload.entity_type=="teacher" else SchoolClass
    obj=db.get(model,payload.entity_id)
    if not obj or obj.project_id!=pid: raise HTTPException(404)
    obj.unavailable_json=json.dumps(valid_slots(p,payload.slots));db.commit();return {"ok":True}

class SessionLocksIn(BaseModel):
    sessions: list[int] = Field(default_factory=list)
    slots: list[int] = Field(default_factory=list)

@app.post("/api/projects/{pid}/session-locks")
def save_session_locks(pid:int,payload:SessionLocksIn,user:User=Depends(current_user),db:Session=Depends(db_session)):
    project=get_project(pid,user,db)
    maximum=project.days*project.sessions
    session_keys=sorted({int(value) for value in payload.sessions if 0<=int(value)<maximum})
    blocked=[]
    ppd=project.sessions*project.periods_per_session
    for key in session_keys:
        day=key//project.sessions
        session=key%project.sessions
        start=day*ppd+session*project.periods_per_session
        blocked.extend(range(start,start+project.periods_per_session))
    blocked=valid_slots(project,[*blocked,*payload.slots])
    project.blocked_slots_json=json.dumps(blocked)
    affected=db.scalars(select(Lesson).where(
        Lesson.project_id==pid,
        Lesson.slot.in_(blocked),
    )).all() if blocked else []
    fixed_affected=db.scalars(select(FixedLesson).where(
        FixedLesson.project_id==pid,
        FixedLesson.slot.in_(blocked),
    )).all() if blocked else []
    for lesson in affected:
        db.delete(lesson)
    for fixed_lesson in fixed_affected:
        db.delete(fixed_lesson)
    db.commit()
    return {"ok":True,"sessions":session_keys,"removed":len(affected)}

class FixedIn(BaseModel):
    assignment_id:int
    slot:int

@app.post("/api/projects/{pid}/fixed")
def fixed(pid:int,payload:FixedIn,user:User=Depends(current_user),db:Session=Depends(db_session)):
    p=get_project(pid,user,db)
    a=db.get(Assignment,payload.assignment_id)
    if not a or a.project_id!=pid: raise HTTPException(404)
    if payload.slot not in all_slots(p): raise HTTPException(400,"Ô thời khóa biểu không hợp lệ")
    if payload.slot in parse_slots(p.blocked_slots_json): raise HTTPException(409,"Buổi này đang bị khóa")
    for existing in db.scalars(select(FixedLesson).where(FixedLesson.project_id==pid,FixedLesson.assignment_id==a.id)).all():
        db.delete(existing)
    db.add(FixedLesson(project_id=pid,assignment_id=a.id,slot=payload.slot));db.commit();return {"ok":True}

@app.post("/api/projects/{pid}/generate")
def generate(pid:int,user:User=Depends(current_user),db:Session=Depends(db_session)):
    p=get_project(pid,user,db)
    assignments=db.scalars(select(Assignment).where(Assignment.project_id==pid)).all()
    existing=db.scalars(select(Lesson).where(Lesson.project_id==pid)).all()
    assignment_by_id={assignment.id:assignment for assignment in assignments}

    # Rà lại lịch cũ trước mỗi lần xếp. Ràng buộc hoặc nguyện vọng có thể đã
    # thay đổi sau khi lịch được tạo, vì vậy không được coi "đủ tiết" là hợp lệ.
    invalid_lessons=[]
    rebuild_assignment_ids=set()
    for lesson in existing:
        assignment=assignment_by_id.get(lesson.assignment_id)
        if not assignment:
            invalid_lessons.append(lesson)
            continue
        if lesson_slot_error(db,p,assignment,lesson.slot,lesson.id):
            if (assignment.consecutive_pattern or "").strip():
                rebuild_assignment_ids.add(assignment.id)
            else:
                invalid_lessons.append(lesson)

    existing_by_assignment=defaultdict(list)
    for lesson in existing:
        existing_by_assignment[lesson.assignment_id].append(lesson)
    for assignment in assignments:
        lessons_for_assignment=existing_by_assignment[assignment.id]
        if not (assignment.consecutive_pattern or "").strip() or not lessons_for_assignment:
            continue
        slots_for_assignment=[lesson.slot for lesson in lessons_for_assignment]
        if len(slots_for_assignment)!=assignment.periods_per_week or not assignment_pattern_matches(p,assignment,slots_for_assignment):
            rebuild_assignment_ids.add(assignment.id)

    if rebuild_assignment_ids:
        invalid_lessons.extend(
            lesson for lesson in existing
            if lesson.assignment_id in rebuild_assignment_ids
        )
    invalid_lessons=list({lesson.id:lesson for lesson in invalid_lessons}.values())
    locked_invalid=[lesson for lesson in invalid_lessons if lesson.locked]
    if locked_invalid:
        return JSONResponse({
            "ok":False,
            "message":f"Có {len(locked_invalid)} tiết cố định xung đột với ràng buộc hoặc mẫu tiết liền mới. Hãy bỏ cố định hoặc điều chỉnh ràng buộc trước khi xếp lại.",
        },409)
    for lesson in invalid_lessons:
        db.delete(lesson)
    if invalid_lessons:
        db.flush()
        existing=db.scalars(select(Lesson).where(Lesson.project_id==pid)).all()

    expected=sum(a.periods_per_week for a in assignments)
    missing=max(0,expected-len(existing))

    # Từ lần xếp thứ hai trở đi, tuyệt đối giữ nguyên các tiết đang có.
    # Chỉ bổ sung những tiết còn thiếu trong khay; nếu lịch đã đủ thì không làm gì.
    if existing:
        if missing == 0:
            if invalid_lessons:
                db.commit()
            return {
                "ok":True,"score":0,"unscheduled":0,
                "message":"Thời khóa biểu đã đủ tiết. Các vị trí hiện tại được giữ nguyên.",
            }
        result=solve_missing(db,p,tries=160)
        if result["unscheduled"]>0:
            return JSONResponse({
                "ok":False,"score":result["score"],"unscheduled":result["unscheduled"],
                "message":f"Không tìm được vị trí phù hợp cho {result['unscheduled']} tiết trong khay. Các tiết đang có trên lịch được giữ nguyên.",
            },409)
        for aid,slot,locked in result["lessons"]:
            db.add(Lesson(project_id=pid,assignment_id=aid,slot=slot,locked=locked))
        db.commit()
        return {
            "ok":True,"score":result["score"],"unscheduled":0,
            "message":f"Đã xếp bổ sung {len(result['lessons'])} tiết từ khay và giữ nguyên các vị trí còn hợp lệ.",
        }

    # Chỉ khi lịch hoàn toàn trống mới chạy bộ xếp toàn bộ.
    result=solve(db,p,tries=120)
    if result["unscheduled"]>0:
        return JSONResponse({
            "ok":False,"score":result["score"],"unscheduled":result["unscheduled"],
            "message":f"Không tìm được lịch đầy đủ; còn {result['unscheduled']} tiết chưa xếp. Lịch hiện tại được giữ nguyên.",
        },409)
    for l in existing: db.delete(l)
    for aid,slot,locked in result["lessons"]:
        db.add(Lesson(project_id=pid,assignment_id=aid,slot=slot,locked=locked))
    db.commit()
    return {"ok":True,"score":result["score"],"unscheduled":0,"message":f"Đã xếp đầy đủ {len(result['lessons'])} tiết."}

def lesson_slot_error(db:Session,project:Project,assignment:Assignment,slot:int,exclude_lesson_id:Optional[int]=None):
    if slot not in all_slots(project): return "Ô thời khóa biểu không hợp lệ."
    if slot in parse_slots(project.blocked_slots_json): return "Buổi này đã bị khóa và không được xếp tiết."
    teacher=db.get(Teacher,assignment.teacher_id);school_class=db.get(SchoolClass,assignment.class_id);subject=db.get(Subject,assignment.subject_id)
    if not teacher or not school_class or not subject: return "Phân công không còn đầy đủ lớp, môn hoặc giáo viên."
    _,requested_unavailable=accepted_teacher_preferences(db,project.id)
    if slot in (parse_slots(teacher.unavailable_json)|requested_unavailable.get(teacher.id,set())): return "Giáo viên đã đăng ký tránh tiết này."
    if slot in parse_slots(school_class.unavailable_json): return "Lớp không học ở tiết này."
    existing_lessons=db.scalars(select(Lesson).where(Lesson.project_id==project.id)).all()
    existing_lessons=[lesson for lesson in existing_lessons if lesson.id!=exclude_lesson_id]
    for lesson in existing_lessons:
        if lesson.slot!=slot: continue
        other=db.get(Assignment,lesson.assignment_id)
        if other and (other.class_id==assignment.class_id or other.teacher_id==assignment.teacher_id):
            return "Ô đích bị trùng lớp hoặc giáo viên."
    ppd=project.sessions*project.periods_per_session;target_day=slot//ppd
    target_position=slot%ppd;target_session=target_position//project.periods_per_session
    teacher_periods=0;subject_periods=[]
    for lesson in existing_lessons:
        other=db.get(Assignment,lesson.assignment_id)
        if not other or lesson.slot//ppd!=target_day: continue
        if other.teacher_id==assignment.teacher_id: teacher_periods+=1
        position=lesson.slot%ppd
        if position//project.periods_per_session==target_session and other.class_id==assignment.class_id and other.subject_id==assignment.subject_id:
            subject_periods.append(position%project.periods_per_session)
    if teacher_periods>=teacher.max_periods_day: return "Giáo viên đã đạt số tiết tối đa trong ngày."
    run=sorted(subject_periods+[target_position%project.periods_per_session]);longest=current=1
    for left,right in zip(run,run[1:]):
        current=current+1 if right==left+1 else 1;longest=max(longest,current)
    if longest>subject.max_consecutive: return "Vượt số tiết liên tiếp tối đa của môn học."
    return None

class MoveIn(BaseModel):
    lesson_id:int
    slot:int

@app.post("/api/projects/{pid}/move")
def move(pid:int,payload:MoveIn,user:User=Depends(current_user),db:Session=Depends(db_session)):
    project=get_project(pid,user,db);lesson=db.get(Lesson,payload.lesson_id)
    if not lesson or lesson.project_id!=pid: raise HTTPException(404)
    if lesson.locked: return JSONResponse({"ok":False,"message":"Tiết cố định không thể di chuyển."},409)
    assignment=db.get(Assignment,lesson.assignment_id)
    if not assignment or assignment.project_id!=pid:
        return JSONResponse({"ok":False,"message":"Phân công của tiết học không còn tồn tại."},409)
    error=lesson_slot_error(db,project,assignment,payload.slot,lesson.id)
    if error: return JSONResponse({"ok":False,"message":error},409)
    assignment_lessons=db.scalars(select(Lesson).where(Lesson.assignment_id==assignment.id)).all()
    proposed_slots=[payload.slot if item.id==lesson.id else item.slot for item in assignment_lessons]
    if len(proposed_slots)==assignment.periods_per_week and not assignment_pattern_matches(project,assignment,proposed_slots):
        return JSONResponse({"ok":False,"message":f"Vị trí này không giữ đúng mẫu tiết liền {assignment.consecutive_pattern}."},409)
    lesson.slot=payload.slot;db.commit();return {"ok":True}

class ManualLessonIn(BaseModel):
    assignment_id:int
    slot:int

@app.post("/api/projects/{pid}/lessons")
def add_manual_lesson(pid:int,payload:ManualLessonIn,user:User=Depends(current_user),db:Session=Depends(db_session)):
    project=get_project(pid,user,db);assignment=db.get(Assignment,payload.assignment_id)
    if not assignment or assignment.project_id!=pid: raise HTTPException(404)
    scheduled=db.scalar(select(func.count(Lesson.id)).where(Lesson.assignment_id==assignment.id)) or 0
    if scheduled>=assignment.periods_per_week:
        return JSONResponse({"ok":False,"message":"Phân công này đã đủ số tiết/tuần."},409)
    error=lesson_slot_error(db,project,assignment,payload.slot)
    if error: return JSONResponse({"ok":False,"message":error},409)
    if scheduled+1==assignment.periods_per_week:
        current_slots=db.scalars(select(Lesson.slot).where(Lesson.assignment_id==assignment.id)).all()
        if not assignment_pattern_matches(project,assignment,[*current_slots,payload.slot]):
            return JSONResponse({"ok":False,"message":f"Tiết cuối này chưa tạo đúng mẫu tiết liền {assignment.consecutive_pattern}."},409)
    lesson=Lesson(project_id=pid,assignment_id=assignment.id,slot=payload.slot,locked=False)
    db.add(lesson);db.commit();return {"ok":True,"id":lesson.id}

@app.delete("/api/projects/{pid}/lessons/{lesson_id}")
def remove_manual_lesson(pid:int,lesson_id:int,user:User=Depends(current_user),db:Session=Depends(db_session)):
    get_project(pid,user,db);lesson=db.get(Lesson,lesson_id)
    if not lesson or lesson.project_id!=pid: raise HTTPException(404)
    if lesson.locked: return JSONResponse({"ok":False,"message":"Tiết cố định không thể gỡ."},409)
    db.delete(lesson);db.commit();return {"ok":True}

@app.delete("/api/projects/{pid}/assignments/{assignment_id}/lessons")
def return_assignment_to_tray(pid:int,assignment_id:int,user:User=Depends(current_user),db:Session=Depends(db_session)):
    get_project(pid,user,db);assignment=db.get(Assignment,assignment_id)
    if not assignment or assignment.project_id!=pid: raise HTTPException(404)
    lessons=db.scalars(select(Lesson).where(Lesson.project_id==pid,Lesson.assignment_id==assignment_id)).all()
    removable=[lesson for lesson in lessons if not lesson.locked];locked=len(lessons)-len(removable)
    for lesson in removable: db.delete(lesson)
    db.commit()
    message=f"Đã đưa {len(removable)} tiết về khay."
    if locked: message+=f" Còn {locked} tiết cố định được giữ lại."
    return {"ok":True,"removed":len(removable),"locked":locked,"message":message}

@app.delete("/api/projects/{pid}/lessons")
def return_all_to_tray(pid:int,user:User=Depends(current_user),db:Session=Depends(db_session)):
    get_project(pid,user,db);lessons=db.scalars(select(Lesson).where(Lesson.project_id==pid)).all()
    removable=[lesson for lesson in lessons if not lesson.locked];locked=len(lessons)-len(removable)
    for lesson in removable: db.delete(lesson)
    db.commit()
    message=f"Đã đưa {len(removable)} tiết về khay."
    if locked: message+=f" Còn {locked} tiết cố định được giữ lại."
    return {"ok":True,"removed":len(removable),"locked":locked,"message":message}

@app.get("/api/projects/{pid}/data")
def api_data(pid:int,user:User=Depends(current_user),db:Session=Depends(db_session)):
    p=get_project(pid,user,db);return project_data(db,p)

class TeacherAccountIn(BaseModel):
    teacher_id: int
    email: str
    password: str = ""

@app.get("/api/projects/{pid}/teacher-accounts")
def list_teacher_accounts(pid:int,user:User=Depends(current_user),db:Session=Depends(db_session)):
    get_project(pid,user,db)
    teachers=db.scalars(select(Teacher).where(Teacher.project_id==pid).order_by(Teacher.name)).all()
    accounts=db.scalars(select(User).where(User.role=="teacher",User.teacher_id.in_([x.id for x in teachers]))).all() if teachers else []
    account_by_teacher={x.teacher_id:x for x in accounts}
    return {"items":[{
        "teacher_id":teacher.id,
        "teacher_name":teacher.name,
        "account_id":account_by_teacher[teacher.id].id if teacher.id in account_by_teacher else None,
        "email":account_by_teacher[teacher.id].email if teacher.id in account_by_teacher else None,
    } for teacher in teachers]}

@app.post("/api/projects/{pid}/teacher-accounts")
def save_teacher_account(pid:int,payload:TeacherAccountIn,user:User=Depends(current_user),db:Session=Depends(db_session)):
    get_project(pid,user,db)
    teacher=db.get(Teacher,payload.teacher_id)
    if not teacher or teacher.project_id!=pid: raise HTTPException(404,"Giáo viên không thuộc bộ thời khóa biểu")
    email=payload.email.lower().strip()
    if not email or "@" not in email: raise HTTPException(400,"Email không hợp lệ")
    account=db.scalar(select(User).where(User.role=="teacher",User.teacher_id==teacher.id))
    email_owner=db.scalar(select(User).where(User.email==email))
    if email_owner and (not account or email_owner.id!=account.id):
        raise HTTPException(409,"Email đã được sử dụng")
    if account:
        account.email=email; account.name=teacher.name
        if payload.password:
            if len(payload.password)<6: raise HTTPException(400,"Mật khẩu phải có ít nhất 6 ký tự")
            account.password_hash=pwd.hash(payload.password)
    else:
        if len(payload.password)<6: raise HTTPException(400,"Mật khẩu phải có ít nhất 6 ký tự")
        account=User(email=email,name=teacher.name,password_hash=pwd.hash(payload.password),role="teacher",teacher_id=teacher.id)
        db.add(account)
    db.commit()
    return {"ok":True,"account_id":account.id}

@app.delete("/api/projects/{pid}/teacher-accounts/{account_id}")
def revoke_teacher_account(pid:int,account_id:int,user:User=Depends(current_user),db:Session=Depends(db_session)):
    get_project(pid,user,db)
    account=db.get(User,account_id)
    teacher=db.get(Teacher,account.teacher_id) if account and account.teacher_id else None
    if not account or account.role!="teacher" or not teacher or teacher.project_id!=pid: raise HTTPException(404)
    db.delete(account);db.commit();return {"ok":True}

def teacher_for_user(user:User,db:Session):
    if user.role!="teacher" or not user.teacher_id: raise HTTPException(403,"Tài khoản giáo viên không hợp lệ")
    teacher=db.get(Teacher,user.teacher_id)
    if not teacher: raise HTTPException(403,"Hồ sơ giáo viên không còn tồn tại")
    project=db.get(Project,teacher.project_id)
    if not project: raise HTTPException(404)
    return teacher,project

def teacher_project_data(db:Session,project:Project,teacher:Teacher):
    data=project_data(db,project)
    assignments=[x for x in data["assignments"] if x["teacher_id"]==teacher.id]
    assignment_ids={x["id"] for x in assignments}
    class_ids={x["class_id"] for x in assignments};subject_ids={x["subject_id"] for x in assignments}
    data["assignments"]=assignments
    data["lessons"]=[x for x in data["lessons"] if x["assignment_id"] in assignment_ids]
    data["teachers"]=[x for x in data["teachers"] if x["id"]==teacher.id]
    data["classes"]=[x for x in data["classes"] if x["id"] in class_ids]
    data["subjects"]=[x for x in data["subjects"] if x["id"] in subject_ids]
    return data

@app.get("/teacher",response_class=HTMLResponse)
def teacher_portal(request:Request,user:User=Depends(current_user),db:Session=Depends(db_session)):
    teacher,project=teacher_for_user(user,db)
    preferences=[x for x in preference_payload(db,project) if x["teacher_id"]==teacher.id]
    return templates.TemplateResponse("teacher_portal.html",{
        "request":request,"user":user,"teacher":teacher,"p":project,
        "data":teacher_project_data(db,project,teacher),"preferences":preferences,
    })

@app.get("/api/teacher/data")
def api_teacher_data(user:User=Depends(current_user),db:Session=Depends(db_session)):
    teacher,project=teacher_for_user(user,db)
    return teacher_project_data(db,project,teacher)

@app.get("/teacher/account",response_class=HTMLResponse)
def teacher_account_page(request:Request,user:User=Depends(current_user),db:Session=Depends(db_session)):
    teacher,project=teacher_for_user(user,db)
    return templates.TemplateResponse("teacher_account.html",{
        "request":request,"user":user,"teacher":teacher,"p":project,"error":None,"success":None,
    })

@app.post("/teacher/account",response_class=HTMLResponse)
def update_teacher_account(
    request:Request,
    email:str=Form(...),
    current_password:str=Form(...),
    new_password:str=Form(""),
    confirm_password:str=Form(""),
    user:User=Depends(current_user),
    db:Session=Depends(db_session),
):
    teacher,project=teacher_for_user(user,db)
    context={"request":request,"user":user,"teacher":teacher,"p":project,"error":None,"success":None}
    if not pwd.verify(current_password,user.password_hash):
        context["error"]="Mật khẩu hiện tại không đúng."
        return templates.TemplateResponse("teacher_account.html",context,status_code=400)
    normalized_email=email.lower().strip()
    if not normalized_email or "@" not in normalized_email:
        context["error"]="Email không hợp lệ."
        return templates.TemplateResponse("teacher_account.html",context,status_code=400)
    email_owner=db.scalar(select(User).where(User.email==normalized_email,User.id!=user.id))
    if email_owner:
        context["error"]="Email đã được sử dụng bởi tài khoản khác."
        return templates.TemplateResponse("teacher_account.html",context,status_code=409)
    if new_password:
        if len(new_password)<6:
            context["error"]="Mật khẩu mới phải có ít nhất 6 ký tự."
            return templates.TemplateResponse("teacher_account.html",context,status_code=400)
        if new_password!=confirm_password:
            context["error"]="Xác nhận mật khẩu mới không khớp."
            return templates.TemplateResponse("teacher_account.html",context,status_code=400)
        user.password_hash=pwd.hash(new_password)
    user.email=normalized_email
    db.commit()
    context["user"]=user
    context["success"]="Thông tin tài khoản đã được cập nhật."
    return templates.TemplateResponse("teacher_account.html",context)

@app.get("/share/{token}",response_class=HTMLResponse)
def shared(token:str,request:Request,db:Session=Depends(db_session)):
    p=db.scalar(select(Project).where(Project.share_token==token))
    if not p: raise HTTPException(404)
    return templates.TemplateResponse("share.html",{"request":request,"p":p,"data":project_data(db,p),"days":DAYS})

@app.get("/preferences/{token}",response_class=HTMLResponse)
def teacher_preferences_page(token:str,request:Request,user:User=Depends(current_user),db:Session=Depends(db_session)):
    p=db.scalar(select(Project).where(Project.share_token==token))
    if not p: raise HTTPException(404)
    teacher,teacher_project=teacher_for_user(user,db)
    if teacher_project.id!=p.id: raise HTTPException(403)
    return templates.TemplateResponse(
        "teacher_preferences.html",
        {"request":request,"p":p,"teacher":teacher,"days":DAYS},
    )

class TeacherPreferenceIn(BaseModel):
    teacher_id: int
    preferred_slots: list[int] = Field(default_factory=list)
    unavailable_slots: list[int] = Field(default_factory=list)
    note: str = ""

@app.post("/api/preferences/{token}")
def submit_teacher_preference(token:str,payload:TeacherPreferenceIn,user:User=Depends(current_user),db:Session=Depends(db_session)):
    p=db.scalar(select(Project).where(Project.share_token==token))
    if not p: raise HTTPException(404)
    teacher,teacher_project=teacher_for_user(user,db)
    if teacher_project.id!=p.id or payload.teacher_id!=teacher.id: raise HTTPException(403,"Không thể gửi nguyện vọng thay giáo viên khác")
    preferred=set(valid_slots(p,payload.preferred_slots))
    unavailable=set(valid_slots(p,payload.unavailable_slots))
    preferred-=unavailable
    note=payload.note.strip()[:1000]
    pending=db.scalar(
        select(TeacherPreference).where(
            TeacherPreference.project_id==p.id,
            TeacherPreference.teacher_id==teacher.id,
            TeacherPreference.status=="pending",
        ).order_by(TeacherPreference.id.desc())
    )
    if pending:
        pending.preferred_json=json.dumps(sorted(preferred))
        pending.unavailable_json=json.dumps(sorted(unavailable))
        pending.note=note
        pending.created_at=datetime.now().isoformat(timespec="seconds")
        preference=pending
    else:
        preference=TeacherPreference(
            project_id=p.id,
            teacher_id=teacher.id,
            preferred_json=json.dumps(sorted(preferred)),
            unavailable_json=json.dumps(sorted(unavailable)),
            note=note,
        )
        db.add(preference)
    db.commit()
    return {"ok":True,"message":"Nguyện vọng đã được gửi đến người xếp thời khóa biểu."}

def preference_payload(db:Session,p:Project):
    rows=db.scalars(
        select(TeacherPreference).where(TeacherPreference.project_id==p.id).order_by(TeacherPreference.id.desc())
    ).all()
    teachers={x.id:x for x in db.scalars(select(Teacher).where(Teacher.project_id==p.id))}
    return [{
        "id":row.id,
        "teacher_id":row.teacher_id,
        "teacher_name":teachers[row.teacher_id].name if row.teacher_id in teachers else "?",
        "preferred_slots":valid_slots(p,parse_slots(row.preferred_json)),
        "unavailable_slots":valid_slots(p,parse_slots(row.unavailable_json)),
        "note":row.note,
        "status":row.status,
        "created_at":row.created_at,
        "reviewed_at":row.reviewed_at,
    } for row in rows]

@app.get("/api/projects/{pid}/preferences")
def list_teacher_preferences(pid:int,user:User=Depends(current_user),db:Session=Depends(db_session)):
    p=get_project(pid,user,db)
    return {"items":preference_payload(db,p),"submission_url":f"/preferences/{p.share_token}"}

class PreferenceReviewIn(BaseModel):
    action: str

@app.post("/api/projects/{pid}/preferences/{preference_id}/review")
def review_teacher_preference(pid:int,preference_id:int,payload:PreferenceReviewIn,user:User=Depends(current_user),db:Session=Depends(db_session)):
    get_project(pid,user,db)
    preference=db.get(TeacherPreference,preference_id)
    if not preference or preference.project_id!=pid: raise HTTPException(404)
    if payload.action not in {"accept","reject"}: raise HTTPException(400,"Thao tác không hợp lệ")
    if preference.status!="pending":
        raise HTTPException(409,"Nguyện vọng này đã được xử lý")
    if payload.action=="accept":
        previous=db.scalars(
            select(TeacherPreference).where(
                TeacherPreference.project_id==pid,
                TeacherPreference.teacher_id==preference.teacher_id,
                TeacherPreference.status=="accepted",
                TeacherPreference.id!=preference.id,
            )
        ).all()
        for row in previous: row.status="superseded"
        preference.status="accepted"
    else:
        preference.status="rejected"
    preference.reviewed_at=datetime.now().isoformat(timespec="seconds")
    db.commit()
    return {"ok":True}

@app.get("/projects/{pid}/export.csv", include_in_schema=False)
def export_csv_legacy(pid:int,user:User=Depends(current_user),db:Session=Depends(db_session)):
    get_project(pid,user,db)
    return RedirectResponse(f"/projects/{pid}/export.xlsx",303)

@app.get("/projects/{pid}/export.xlsx")
def export_excel(pid:int,user:User=Depends(current_user),db:Session=Depends(db_session)):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.worksheet.table import Table, TableStyleInfo

    p=get_project(pid,user,db); data=project_data(db,p)
    workbook=Workbook(); sheet=workbook.active; sheet.title="Thời khóa biểu"
    sheet.sheet_view.showGridLines=False
    sheet.merge_cells("A1:F1"); sheet["A1"]=p.name
    sheet.merge_cells("A2:F2"); sheet["A2"]=p.school_name
    sheet["A1"].font=Font(name="Aptos Display",size=18,bold=True,color="FFFFFF")
    sheet["A1"].fill=PatternFill("solid",fgColor="1D4ED8")
    sheet["A1"].alignment=Alignment(horizontal="left",vertical="center")
    sheet["A2"].font=Font(name="Aptos",size=11,color="475467")
    sheet["A2"].alignment=Alignment(horizontal="left",vertical="center")
    sheet.row_dimensions[1].height=30; sheet.row_dimensions[2].height=22

    headers=["Lớp","Thứ","Buổi","Tiết","Môn","Giáo viên"]
    sheet.append([]); sheet.append(headers)
    header_fill=PatternFill("solid",fgColor="DBEAFE")
    header_border=Border(bottom=Side(style="thin",color="93C5FD"))
    for cell in sheet[4]:
        cell.font=Font(name="Aptos",bold=True,color="1E3A8A")
        cell.fill=header_fill; cell.border=header_border
        cell.alignment=Alignment(vertical="center")
    sheet.row_dimensions[4].height=24

    assignments={item["id"]:item for item in data["assignments"]}
    rows=[]
    for lesson in data["lessons"]:
        assignment=assignments.get(lesson["assignment_id"])
        if not assignment:
            continue
        day,session,period=slot_meta(p,lesson["slot"])
        rows.append((
            lesson["slot"],assignment["class_name"],DAYS[day],
            "Sáng" if session==0 else "Chiều",period+1,
            assignment["subject_name"],assignment["teacher_name"],
        ))
    rows.sort(key=lambda row:(row[0],row[1]))
    for _,class_name,day_name,session_name,period,subject_name,teacher_name in rows:
        sheet.append([class_name,day_name,session_name,period,subject_name,teacher_name])

    last_row=4+len(rows)
    if rows:
        table=Table(displayName="ThoiKhoaBieu",ref=f"A4:F{last_row}")
        table.tableStyleInfo=TableStyleInfo(
            name="TableStyleMedium2",showFirstColumn=False,showLastColumn=False,
            showRowStripes=True,showColumnStripes=False,
        )
        sheet.add_table(table)
    else:
        sheet.merge_cells("A5:F5"); sheet["A5"]="Chưa có tiết học nào được xếp."
        sheet["A5"].font=Font(name="Aptos",italic=True,color="667085")
        sheet["A5"].alignment=Alignment(horizontal="center")
        sheet.auto_filter.ref="A4:F4"

    widths={"A":16,"B":14,"C":12,"D":10,"E":24,"F":24}
    for column,width in widths.items(): sheet.column_dimensions[column].width=width
    sheet.freeze_panes="A5"; sheet.auto_filter.ref=f"A4:F{last_row}"
    sheet.print_title_rows="1:4"; sheet.page_setup.orientation="landscape"
    sheet.page_setup.fitToWidth=1; sheet.sheet_properties.pageSetUpPr.fitToPage=True
    sheet.print_area=f"A1:F{max(last_row,5)}"
    sheet["D5" if rows else "D4"].number_format="0"

    output=io.BytesIO(); workbook.save(output); output.seek(0)
    encoded_filename=quote(f"{p.name}.xlsx",safe="")
    disposition=f"attachment; filename=thoi-khoa-bieu.xlsx; filename*=UTF-8''{encoded_filename}"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":disposition},
    )

def project_data(db:Session,p:Project):
    deps=db.scalars(select(Department).where(Department.project_id==p.id)).all()
    subs=db.scalars(select(Subject).where(Subject.project_id==p.id)).all()
    teas=db.scalars(select(Teacher).where(Teacher.project_id==p.id)).all()
    grades=db.scalars(select(Grade).where(Grade.project_id==p.id)).all()
    classes=db.scalars(select(SchoolClass).where(SchoolClass.project_id==p.id)).all()
    assignments=db.scalars(select(Assignment).where(Assignment.project_id==p.id)).all()
    lessons=db.scalars(select(Lesson).where(Lesson.project_id==p.id)).all()
    sm={x.id:x for x in subs};tm={x.id:x for x in teas};cm={x.id:x for x in classes}
    assigned_teacher_ids={x.teacher_id for x in assignments};assigned_subject_ids={x.subject_id for x in assignments};assigned_class_ids={x.class_id for x in assignments}
    return {
      "project":{"id":p.id,"name":p.name,"school_name":p.school_name,"days":p.days,"sessions":p.sessions,"periods":p.periods_per_session,"share_token":p.share_token,"blocked_slots":valid_slots(p,parse_slots(p.blocked_slots_json))},
      "departments":[{"id":x.id,"name":x.name} for x in deps],
      "subjects":[{"id":x.id,"name":x.name,"short_name":x.short_name,"max_consecutive":x.max_consecutive} for x in subs],
      "teachers":[{"id":x.id,"name":x.name,"short_name":x.short_name,"department_id":x.department_id,"max_periods_day":x.max_periods_day,"unavailable":list(parse_slots(x.unavailable_json))} for x in teas],
      "grades":[{"id":x.id,"name":x.name} for x in grades],
      "classes":[{"id":x.id,"name":x.name,"grade_id":x.grade_id,"unavailable":list(parse_slots(x.unavailable_json))} for x in classes],
      "assignments":[{"id":x.id,"class_id":x.class_id,"subject_id":x.subject_id,"teacher_id":x.teacher_id,"periods_per_week":x.periods_per_week,"consecutive_pattern":x.consecutive_pattern,"class_name":cm.get(x.class_id).name if cm.get(x.class_id) else "?","subject_name":sm.get(x.subject_id).name if sm.get(x.subject_id) else "?","subject_short":sm.get(x.subject_id).short_name if sm.get(x.subject_id) else "?","teacher_name":tm.get(x.teacher_id).name if tm.get(x.teacher_id) else "?","teacher_short":tm.get(x.teacher_id).short_name if tm.get(x.teacher_id) else "?"} for x in assignments],
      "lessons":[{"id":x.id,"assignment_id":x.assignment_id,"slot":x.slot,"locked":x.locked} for x in lessons],
      "coverage":{
        "unassigned_teachers":[{"id":x.id,"name":x.name} for x in teas if x.id not in assigned_teacher_ids],
        "unassigned_subjects":[{"id":x.id,"name":x.name} for x in subs if x.id not in assigned_subject_ids],
        "unassigned_classes":[{"id":x.id,"name":x.name} for x in classes if x.id not in assigned_class_ids],
      }
    }

def ga_schedule(db:Session,p:Project,mode:str,tries:int=120):
    assignments=db.scalars(select(Assignment).where(Assignment.project_id==p.id)).all()
    teachers={x.id:x for x in db.scalars(select(Teacher).where(Teacher.project_id==p.id))}
    classes={x.id:x for x in db.scalars(select(SchoolClass).where(SchoolClass.project_id==p.id))}
    subjects={x.id:x for x in db.scalars(select(Subject).where(Subject.project_id==p.id))}
    existing=db.scalars(select(Lesson).where(Lesson.project_id==p.id)).all()
    existing_counts=Counter(x.assignment_id for x in existing)
    fixed={x.assignment_id:x.slot for x in db.scalars(select(FixedLesson).where(FixedLesson.project_id==p.id))}
    requested_preferred,requested_unavailable=accepted_teacher_preferences(db,p.id)
    global_blocked=parse_slots(p.blocked_slots_json)
    slots=all_slots(p)
    ppd=p.sessions*p.periods_per_session
    if not assignments:
        return {"lessons":[],"unscheduled":0,"score":0}

    task_rows=[]
    for assignment in assignments:
        remaining=max(0,assignment.periods_per_week-existing_counts[assignment.id])
        if remaining<=0:
            continue
        use_full_pattern=(
            mode=="full"
            or (
                bool((assignment.consecutive_pattern or "").strip())
                and existing_counts[assignment.id]==0
            )
        )
        if use_full_pattern:
            try:
                groups=consecutive_groups(assignment.consecutive_pattern,assignment.periods_per_week)
                if any(size>subjects[assignment.subject_id].max_consecutive for size in groups):
                    groups=[1]*assignment.periods_per_week
            except (ValueError,KeyError):
                groups=[1]*assignment.periods_per_week
            explicit=bool((assignment.consecutive_pattern or "").strip())
            for group_index,size in enumerate(groups):
                if group_index>=remaining:
                    break
                task_rows.append((assignment,group_index,size,explicit,fixed.get(assignment.id) if group_index==0 else None))
        else:
            for group_index in range(remaining):
                task_rows.append((assignment,group_index,1,False,fixed.get(assignment.id) if group_index==0 else None))

    if not task_rows:
        return {"lessons":[],"unscheduled":0,"score":0}

    random.shuffle(task_rows)
    task_rows.sort(key=lambda task:(
        1 if task[4] is not None and task[1]==0 else 0,
        task[2],
        len(parse_slots(teachers[task[0].teacher_id].unavailable_json))+len(parse_slots(classes[task[0].class_id].unavailable_json)),
        -existing_counts[task[0].id],
    ),reverse=True)

    def valid_start_slots(size:int):
        return [slot for slot in slots if (slot % ppd) % p.periods_per_session + size <= p.periods_per_session]

    starts_by_size={}
    def start_pool(size:int):
        pool=starts_by_size.get(size)
        if pool is None:
            pool=valid_start_slots(size)
            starts_by_size[size]=pool
        return pool

    def evaluate(genes:list[int|None]):
        teacher_busy=defaultdict(set)
        class_busy=defaultdict(set)
        assignment_busy=defaultdict(set)
        teacher_day=Counter()
        class_sub_day=Counter()
        class_sub_slots=defaultdict(set)
        placed=[]
        unscheduled=0
        gene_miss=0.0

        for lesson in existing:
            assignment=next((x for x in assignments if x.id==lesson.assignment_id),None)
            if not assignment:
                continue
            day=lesson.slot//ppd
            teacher_busy[assignment.teacher_id].add(lesson.slot)
            class_busy[assignment.class_id].add(lesson.slot)
            assignment_busy[assignment.id].add(lesson.slot)
            teacher_day[(assignment.teacher_id,day)]+=1
            class_sub_day[(assignment.class_id,assignment.subject_id,day)]+=1
            class_sub_slots[(assignment.class_id,assignment.subject_id,day)].add(lesson.slot%ppd)

        for index,task in enumerate(task_rows):
            assignment,group_index,size,explicit,forced=task
            gene=forced if forced is not None else genes[index]
            candidate_starts=[forced] if forced is not None else start_pool(size)
            tu=parse_slots(teachers[assignment.teacher_id].unavailable_json)|requested_unavailable.get(assignment.teacher_id,set())
            cu=parse_slots(classes[assignment.class_id].unavailable_json)
            best_slot=None
            best_score=None
            for slot in candidate_starts:
                if slot is None:
                    continue
                day=slot//ppd
                position=slot%ppd
                session=position//p.periods_per_session
                period=position%p.periods_per_session
                if period+size>p.periods_per_session:
                    continue
                group_slots=list(range(slot,slot+size))
                if any(candidate//ppd!=day or (candidate%ppd)//p.periods_per_session!=session for candidate in group_slots):
                    continue
                if any(candidate in global_blocked or candidate in tu or candidate in cu or candidate in teacher_busy[assignment.teacher_id] or candidate in class_busy[assignment.class_id] for candidate in group_slots):
                    continue
                if teacher_day[(assignment.teacher_id,day)]+size>teachers[assignment.teacher_id].max_periods_day:
                    continue
                if explicit:
                    neighbors=[]
                    if period>0:
                        neighbors.append(slot-1)
                    if period+size<p.periods_per_session:
                        neighbors.append(slot+size)
                    if any(neighbor in assignment_busy[assignment.id] for neighbor in neighbors):
                        continue
                existing_periods=[
                    candidate%p.periods_per_session
                    for candidate in class_sub_slots[(assignment.class_id,assignment.subject_id,day)]
                    if candidate//p.periods_per_session==session
                ]
                run=sorted(set(existing_periods+list(range(period,period+size))))
                longest=current=1
                for left,right in zip(run,run[1:]):
                    current=current+1 if right==left+1 else 1
                    longest=max(longest,current)
                if longest>subjects[assignment.subject_id].max_consecutive:
                    continue
                score=class_sub_day[(assignment.class_id,assignment.subject_id,day)]*8+sum((candidate%p.periods_per_session)*0.15 for candidate in group_slots)
                preferred=requested_preferred.get(assignment.teacher_id,set())
                if preferred:
                    score+=sum(-4 if candidate in preferred else 1.5 for candidate in group_slots)
                for neighbor in (slot-1,slot+size):
                    if neighbor in teacher_busy[assignment.teacher_id]:
                        score-=1.2
                if gene is not None:
                    if slot==gene:
                        score-=8
                    else:
                        score+=abs(slot-gene)*0.05
                if best_score is None or score<best_score:
                    best_score=score
                    best_slot=slot
            if best_slot is None:
                unscheduled+=size
                continue
            day=best_slot//ppd
            gene_value=forced if forced is not None else genes[index]
            if gene_value is not None and best_slot!=gene_value:
                gene_miss+=abs(best_slot-gene_value)
            for offset,slot in enumerate(range(best_slot,best_slot+size)):
                teacher_busy[assignment.teacher_id].add(slot)
                class_busy[assignment.class_id].add(slot)
                assignment_busy[assignment.id].add(slot)
                class_sub_slots[(assignment.class_id,assignment.subject_id,day)].add(slot%ppd)
                placed.append((assignment.id,slot,forced is not None and group_index==0 and offset==0))
            teacher_day[(assignment.teacher_id,day)]+=size
            class_sub_day[(assignment.class_id,assignment.subject_id,day)]+=size

        score=unscheduled*10000+gene_miss*0.05
        for (cid,sid,day),n in class_sub_day.items():
            score+=max(0,n-1)*10
        for tid,busy in teacher_busy.items():
            for day in range(p.days):
                xs=sorted(slot%ppd for slot in busy if slot//ppd==day)
                if xs:
                    score+=(xs[-1]-xs[0]+1-len(xs))*2
        return {"lessons":placed,"unscheduled":unscheduled,"score":round(score,2)}

    def genes_from_candidate(candidate):
        genes=[None]*len(task_rows)
        by_assignment=defaultdict(list)
        for assignment_id,slot,_locked in candidate["lessons"]:
            by_assignment[assignment_id].append(slot)
        cursor=defaultdict(int)
        for index,task in enumerate(task_rows):
            assignment,group_index,size,explicit,forced=task
            if forced is not None:
                genes[index]=forced
                continue
            slots_for_assignment=by_assignment.get(assignment.id,[])
            if cursor[assignment.id] < len(slots_for_assignment):
                genes[index]=slots_for_assignment[cursor[assignment.id]]
                cursor[assignment.id]+=1
        return genes

    def random_gene(task):
        assignment,group_index,size,explicit,forced=task
        if forced is not None:
            return forced
        pool=start_pool(size)
        return random.choice(pool) if pool else None

    def mutate(genes):
        child=genes[:]
        for index,task in enumerate(task_rows):
            assignment,group_index,size,explicit,forced=task
            if forced is not None:
                child[index]=forced
                continue
            if random.random()<0.15:
                child[index]=random_gene(task) if random.random()<0.9 else None
        return child

    def crossover(left,right):
        child=[]
        for index,task in enumerate(task_rows):
            assignment,group_index,size,explicit,forced=task
            if forced is not None:
                child.append(forced)
            elif random.random()<0.5:
                child.append(left[index])
            else:
                child.append(right[index])
        return child

    population_size=max(18,min(40,max(12,len(task_rows))))
    generations=max(12,min(60,max(tries//3,18)))
    elite_count=max(2,population_size//5)

    seed_candidate=evaluate([None]*len(task_rows))
    best_candidate=seed_candidate
    population=[genes_from_candidate(seed_candidate)]
    for _ in range(population_size-1):
        population.append([random_gene(task) for task in task_rows])

    evaluated=[]
    for genes in population:
        candidate=evaluate(genes)
        evaluated.append((candidate,genes))
        if candidate["score"]<best_candidate["score"]:
            best_candidate=candidate

    for _ in range(generations):
        evaluated.sort(key=lambda item:(item[0]["score"],item[0]["unscheduled"]))
        elites=[genes for _candidate,genes in evaluated[:elite_count]]
        if evaluated[0][0]["score"]<best_candidate["score"]:
            best_candidate=evaluated[0][0]
        next_population=elites[:]
        while len(next_population)<population_size:
            pool=evaluated[:max(6,population_size//2)]
            parent1=random.choice(pool)[1]
            parent2=random.choice(pool)[1]
            child=mutate(crossover(parent1,parent2))
            next_population.append(child)
        evaluated=[]
        for genes in next_population:
            candidate=evaluate(genes)
            evaluated.append((candidate,genes))
            if candidate["score"]<best_candidate["score"]:
                best_candidate=candidate

    if evaluated:
        evaluated.sort(key=lambda item:(item[0]["score"],item[0]["unscheduled"]))
        if evaluated[0][0]["score"]<best_candidate["score"]:
            best_candidate=evaluated[0][0]
    return best_candidate

def solve_missing(db:Session,p:Project,tries=120):
    """Giữ nguyên các Lesson hiện có và chỉ xếp số tiết còn thiếu."""
    return ga_schedule(db,p,mode="missing",tries=tries)

def solve(db:Session,p:Project,tries=80):
    return ga_schedule(db,p,mode="full",tries=tries)

def seed_project(db:Session,p:Project):
    d1=Department(project_id=p.id,name="Tổ Toán - Tin");d2=Department(project_id=p.id,name="Tổ Ngữ văn")
    db.add_all([d1,d2]);db.flush()
    s1=Subject(project_id=p.id,name="Toán",short_name="TOÁN",max_consecutive=2);s2=Subject(project_id=p.id,name="Ngữ văn",short_name="VĂN",max_consecutive=2);s3=Subject(project_id=p.id,name="Tin học",short_name="TIN",max_consecutive=1)
    db.add_all([s1,s2,s3]);db.flush()
    t1=Teacher(project_id=p.id,department_id=d1.id,name="Nguyễn Văn An",short_name="An",max_periods_day=4);t2=Teacher(project_id=p.id,department_id=d2.id,name="Trần Thị Bình",short_name="Bình",max_periods_day=4);t3=Teacher(project_id=p.id,department_id=d1.id,name="Lê Minh Châu",short_name="Châu",max_periods_day=4)
    db.add_all([t1,t2,t3]);db.flush()
    g=Grade(project_id=p.id,name="Khối 10");db.add(g);db.flush()
    c1=SchoolClass(project_id=p.id,grade_id=g.id,name="10A1");c2=SchoolClass(project_id=p.id,grade_id=g.id,name="10A2");db.add_all([c1,c2]);db.flush()
    for c in [c1,c2]:
        db.add_all([Assignment(project_id=p.id,class_id=c.id,subject_id=s1.id,teacher_id=t1.id,periods_per_week=4),Assignment(project_id=p.id,class_id=c.id,subject_id=s2.id,teacher_id=t2.id,periods_per_week=3),Assignment(project_id=p.id,class_id=c.id,subject_id=s3.id,teacher_id=t3.id,periods_per_week=2)])
    db.commit()

def ensure_demo():
    db=SessionLocal()
    try:
        user=db.scalar(select(User).where(User.email==DEFAULT_ADMIN_EMAIL))
        existing_admin=db.scalar(select(User).where(User.role=="admin").order_by(User.id.asc()))
        legacy_user=db.scalar(
            select(User).where(User.email.in_(LEGACY_ADMIN_EMAILS)).order_by(User.id.asc())
        )
        if user is not None:
            if existing_admin is None:
                user.name="Quản trị viên"
                user.role="admin"
                user.password_hash=pwd.hash(DEFAULT_ADMIN_PASSWORD)
                db.commit()
        elif legacy_user is not None and (legacy_user.role=="admin" or existing_admin is None):
            # Chuyển một lần tài khoản mặc định cũ, không đặt lại mật khẩu ở
            # các lần khởi động sau để quản trị viên vẫn có thể tự đổi mật khẩu.
            legacy_user.email=DEFAULT_ADMIN_EMAIL
            legacy_user.name="Quản trị viên"
            legacy_user.role="admin"
            legacy_user.password_hash=pwd.hash(DEFAULT_ADMIN_PASSWORD)
            user=legacy_user
            db.commit()
        elif existing_admin is not None:
            user=existing_admin
        else:
            user=User(email=DEFAULT_ADMIN_EMAIL,name="Quản trị viên",password_hash=pwd.hash(DEFAULT_ADMIN_PASSWORD),role="admin")
            db.add(user);db.commit()
            p=Project(owner_id=user.id,name="TKB học kỳ I",school_name="THPT Demo",days=6,sessions=2,periods_per_session=5)
            db.add(p);db.commit();seed_project(db,p)
    finally:
        db.close()
ensure_demo()
