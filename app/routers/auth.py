from __future__ import annotations

from fastapi import APIRouter
from app.services.runtime import *

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(db_session)):
    raw = request.cookies.get("session")
    if raw:
        try:
            data = signer.loads(raw, max_age=SESSION_TTL_SECONDS)
            user = db.get(User, int(data["uid"]))
            if user and int(data.get("sv", -1)) == user.session_version:
                destination = (
                    "/teacher"
                    if user.role == "teacher"
                    else ("/projects" if is_admin(user) else "/logout")
                )
                return RedirectResponse(destination, 303)
        except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
            pass
    return templates.TemplateResponse("landing.html", {"request": request})

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        "auth.html", {"request": request, "mode": "login", "error": None}
    )

@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(db_session),
):
    normalized_email = email.lower().strip()
    ip_key = client_rate_limit_key(request)
    if rate_limit_blocked(
        "login_ip", ip_key, limit=20, window_seconds=10 * 60
    ) or rate_limit_blocked(
        "login_email", normalized_email, limit=8, window_seconds=10 * 60
    ):
        return templates.TemplateResponse(
            "auth.html",
            {
                "request": request,
                "mode": "login",
                "error": "Bạn đã thử đăng nhập sai quá nhiều lần. Vui lòng đợi vài phút rồi thử lại.",
            },
            status_code=429,
        )
    user = db.scalar(select(User).where(User.email == normalized_email))
    if not user or not pwd.verify(password, user.password_hash):
        ip_limited = rate_limit_exceeded(
            "login_ip", ip_key, limit=20, window_seconds=10 * 60
        )
        email_limited = rate_limit_exceeded(
            "login_email", normalized_email, limit=8, window_seconds=10 * 60
        )
        if ip_limited or email_limited:
            return templates.TemplateResponse(
                "auth.html",
                {
                    "request": request,
                    "mode": "login",
                    "error": "Bạn đã thử đăng nhập sai quá nhiều lần. Vui lòng đợi vài phút rồi thử lại.",
                },
                status_code=429,
            )
        return templates.TemplateResponse(
            "auth.html",
            {
                "request": request,
                "mode": "login",
                "error": "Email hoặc mật khẩu không đúng",
            },
            status_code=400,
        )
    # Chỉ lỗi đăng nhập mới được tính vào rate-limit. Đăng nhập đúng xóa bucket
    # theo email để các lần đăng nhập hợp lệ không tự khóa tài khoản.
    clear_rate_limit_bucket("login_email", normalized_email)
    destination = (
        "/teacher"
        if user.role == "teacher"
        else ("/projects" if is_admin(user) else "/logout")
    )
    user.last_seen = _utc_now_iso()
    db.commit()
    res = RedirectResponse(destination, 303)
    set_session_cookie(res, user)
    return res

@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    captcha_challenge, captcha_token = new_captcha("registration")
    return templates.TemplateResponse(
        "auth.html",
        {
            "request": request,
            "mode": "register",
            "error": None,
            "captcha_challenge": captcha_challenge,
            "captcha_token": captcha_token,
            "form_values": {},
        },
    )

@router.post("/register")
def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    captcha_answer: str = Form(...),
    captcha_token: str = Form(...),
    human_confirm: Optional[str] = Form(None),
    website: str = Form(""),
    db: Session = Depends(db_session),
):
    name = name.strip()
    email = email.lower().strip()
    fresh_challenge, fresh_captcha_token = new_captcha("registration")
    context = {
        "request": request,
        "mode": "register",
        "error": None,
        "captcha_challenge": fresh_challenge,
        "captcha_token": fresh_captcha_token,
        "form_values": {"name": name, "email": email},
    }
    if rate_limit_exceeded(
        "register_ip", client_rate_limit_key(request), limit=12, window_seconds=15 * 60
    ) or rate_limit_exceeded("register_email", email, limit=5, window_seconds=15 * 60):
        context["error"] = (
            "Có quá nhiều yêu cầu đăng ký. Vui lòng đợi vài phút rồi thử lại."
        )
        return templates.TemplateResponse("auth.html", context, status_code=429)
    if (
        website.strip()
        or human_confirm != "yes"
        or not captcha_is_valid(captcha_token, captcha_answer, "registration")
    ):
        context["error"] = (
            "Xác minh bảo mật không hợp lệ hoặc thao tác quá nhanh. Hãy hoàn thành thử thách mới."
        )
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if not name:
        context["error"] = "Tên giáo viên không được để trống"
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if len(name) > 120:
        context["error"] = "Tên giáo viên không được vượt quá 120 ký tự"
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if len(email) > 255:
        context["error"] = "Email không được vượt quá 255 ký tự"
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if len(password) < MIN_PASSWORD_LENGTH:
        context["error"] = f"Mật khẩu phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự"
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if password != password_confirm:
        context["error"] = "Hai lần nhập mật khẩu không khớp"
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if not email or "@" not in email:
        context["error"] = "Email không hợp lệ"
        return templates.TemplateResponse("auth.html", context, status_code=400)
    if db.scalar(select(User).where(User.email == email)):
        context["error"] = "Email đã tồn tại"
        return templates.TemplateResponse("auth.html", context, status_code=400)

    now = datetime.now(timezone.utc)
    for expired in db.scalars(
        select(RegistrationVerification).where(
            RegistrationVerification.expires_at <= now.isoformat()
        )
    ).all():
        db.delete(expired)
    db.flush()

    email_verification = db.scalar(
        select(RegistrationVerification)
        .where(RegistrationVerification.email == email)
        .with_for_update()
    )
    if (
        email_verification
        and datetime.fromisoformat(email_verification.resend_available_at) > now
    ):
        context["error"] = (
            "Mã OTP vừa được gửi tới email này. Vui lòng chờ 60 giây trước khi gửi lại."
        )
        return templates.TemplateResponse("auth.html", context, status_code=429)

    otp = f"{secrets.randbelow(1_000_000):06d}"
    nonce = secrets.token_urlsafe(32)
    try:
        if not send_registration_otp_email(email, otp, name):
            raise RuntimeError("SMTP chưa được cấu hình")
    except (OSError, smtplib.SMTPException, RuntimeError, ValueError) as exc:
        logger.exception("Could not send registration OTP to %s: %s", email, exc)
        context["error"] = (
            "Chưa thể gửi mã OTP. Vui lòng kiểm tra email hoặc thử lại sau."
        )
        return templates.TemplateResponse("auth.html", context, status_code=503)

    if email_verification is not None:
        db.delete(email_verification)
        db.flush()
    verification = RegistrationVerification(
        email=email,
        name=name,
        password_hash=pwd.hash(password),
        otp_hash=registration_otp_hash(email, otp),
        token_hash=hashlib.sha256(nonce.encode()).hexdigest(),
        expires_at=(now + timedelta(seconds=REGISTRATION_OTP_TTL_SECONDS)).isoformat(),
        resend_available_at=(
            now + timedelta(seconds=REGISTRATION_OTP_RESEND_SECONDS)
        ).isoformat(),
        attempt_count=0,
    )
    db.add(verification)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        context["error"] = (
            "Email này đang được xác minh ở một phiên khác. Hãy thử lại sau."
        )
        return templates.TemplateResponse("auth.html", context, status_code=409)
    verification_token = registration_signer.dumps(
        {"id": verification.id, "nonce": nonce}
    )
    resend_challenge, resend_captcha = new_captcha("registration_resend")
    return templates.TemplateResponse(
        "auth.html",
        {
            "request": request,
            "mode": "register_otp",
            "error": None,
            "verification_token": verification_token,
            "masked_email": mask_email(email),
            "target_teacher_name": name,
            "captcha_challenge": resend_challenge,
            "captcha_token": resend_captcha,
        },
    )

@router.post("/register/verify", response_class=HTMLResponse)
def verify_registration_otp(
    request: Request,
    verification_token: str = Form(...),
    otp: str = Form(...),
    db: Session = Depends(db_session),
):
    verification = registration_verification_for_token(
        verification_token, db, lock=True
    )
    now = datetime.now(timezone.utc)
    if not verification or datetime.fromisoformat(verification.expires_at) <= now:
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                verification,
                verification_token,
                "Mã OTP không hợp lệ hoặc đã hết hạn. Hãy đăng ký lại.",
            ),
            status_code=400,
        )
    if verification.attempt_count >= REGISTRATION_OTP_MAX_ATTEMPTS:
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                verification,
                verification_token,
                "Bạn đã nhập sai quá số lần cho phép. Hãy gửi lại mã OTP mới.",
            ),
            status_code=429,
        )
    normalized_otp = otp.strip()
    if (
        not normalized_otp.isdigit()
        or len(normalized_otp) != 6
        or not hmac.compare_digest(
            verification.otp_hash,
            registration_otp_hash(verification.email, normalized_otp),
        )
    ):
        verification.attempt_count += 1
        remaining = max(0, REGISTRATION_OTP_MAX_ATTEMPTS - verification.attempt_count)
        db.commit()
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                verification,
                verification_token,
                f"Mã OTP không đúng. Bạn còn {remaining} lần thử.",
            ),
            status_code=400,
        )

    if db.scalar(select(User.id).where(User.email == verification.email)) is not None:
        db.delete(verification)
        db.commit()
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                None,
                verification_token,
                "Email này đã được đăng ký. Hãy chuyển sang trang đăng nhập.",
            ),
            status_code=409,
        )

    teacher_name = verification.name.strip()
    # Đăng ký chỉ tạo tài khoản đăng nhập. Không tạo Teacher trong bất kỳ
    # project nào; hồ sơ giáo viên phục vụ xếp lịch chỉ do quản trị viên tạo/cấu hình.
    user = User(
        name=teacher_name,
        email=verification.email,
        password_hash=verification.password_hash,
        role="teacher",
    )
    db.add(user)
    try:
        db.flush()
        db.delete(verification)
        db.commit()
    except IntegrityError:
        db.rollback()
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                None,
                verification_token,
                "Email này vừa được tài khoản khác sử dụng. Hãy đăng nhập hoặc đăng ký lại.",
            ),
            status_code=409,
        )
    response = RedirectResponse("/teacher", 303)
    set_session_cookie(response, user)
    return response

@router.post("/register/resend", response_class=HTMLResponse)
def resend_registration_otp(
    request: Request,
    verification_token: str = Form(...),
    captcha_answer: str = Form(...),
    captcha_token: str = Form(...),
    human_confirm: Optional[str] = Form(None),
    website: str = Form(""),
    db: Session = Depends(db_session),
):
    verification = registration_verification_for_token(
        verification_token, db, lock=True
    )
    if not verification:
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                None,
                verification_token,
                "Phiên xác minh không còn hợp lệ. Hãy đăng ký lại.",
            ),
            status_code=400,
        )
    if rate_limit_exceeded(
        "register_resend_ip",
        client_rate_limit_key(request),
        limit=10,
        window_seconds=15 * 60,
    ) or rate_limit_exceeded(
        "register_resend_email", verification.email, limit=5, window_seconds=15 * 60
    ):
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                verification,
                verification_token,
                "Bạn đã yêu cầu gửi lại mã quá nhiều lần. Vui lòng đợi rồi thử lại.",
            ),
            status_code=429,
        )
    if (
        website.strip()
        or human_confirm != "yes"
        or not captcha_is_valid(captcha_token, captcha_answer, "registration_resend")
    ):
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                verification,
                verification_token,
                "Xác minh bảo mật không đúng hoặc thao tác quá nhanh.",
            ),
            status_code=400,
        )
    now = datetime.now(timezone.utc)
    if datetime.fromisoformat(verification.resend_available_at) > now:
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                verification,
                verification_token,
                "Vui lòng chờ đủ 60 giây trước khi yêu cầu mã mới.",
            ),
            status_code=429,
        )
    otp = f"{secrets.randbelow(1_000_000):06d}"
    try:
        if not send_registration_otp_email(
            verification.email,
            otp,
            verification.name,
        ):
            raise RuntimeError("SMTP chưa được cấu hình")
    except (OSError, smtplib.SMTPException, RuntimeError, ValueError) as exc:
        logger.exception(
            "Could not resend registration OTP to %s: %s", verification.email, exc
        )
        return templates.TemplateResponse(
            "auth.html",
            registration_otp_context(
                request,
                verification,
                verification_token,
                "Chưa thể gửi lại mã OTP. Vui lòng thử lại sau.",
            ),
            status_code=503,
        )
    verification.otp_hash = registration_otp_hash(verification.email, otp)
    nonce = secrets.token_urlsafe(32)
    verification.token_hash = hashlib.sha256(nonce.encode()).hexdigest()
    verification.expires_at = (
        now + timedelta(seconds=REGISTRATION_OTP_TTL_SECONDS)
    ).isoformat()
    verification.resend_available_at = (
        now + timedelta(seconds=REGISTRATION_OTP_RESEND_SECONDS)
    ).isoformat()
    verification.attempt_count = 0
    db.commit()
    refreshed_token = registration_signer.dumps({"id": verification.id, "nonce": nonce})
    return templates.TemplateResponse(
        "auth.html",
        registration_otp_context(
            request,
            verification,
            refreshed_token,
        ),
    )

@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request):
    captcha_challenge, captcha_token = new_captcha()
    return templates.TemplateResponse(
        "forgot_password.html",
        {
            "request": request,
            "captcha_challenge": captcha_challenge,
            "captcha_token": captcha_token,
            "error": None,
            "submitted": False,
            "dev_reset_link": None,
        },
    )

@router.post("/forgot-password", response_class=HTMLResponse)
def forgot_password(
    request: Request,
    email: str = Form(...),
    not_robot: Optional[str] = Form(None),
    captcha_answer: str = Form(...),
    captcha_token: str = Form(...),
    db: Session = Depends(db_session),
):
    normalized_email = email.lower().strip()
    if rate_limit_exceeded(
        "forgot_ip", client_rate_limit_key(request), limit=8, window_seconds=15 * 60
    ) or rate_limit_exceeded(
        "forgot_email", normalized_email, limit=4, window_seconds=30 * 60
    ):
        fresh_challenge, fresh_token = new_captcha()
        return templates.TemplateResponse(
            "forgot_password.html",
            {
                "request": request,
                "captcha_challenge": fresh_challenge,
                "captcha_token": fresh_token,
                "error": "Bạn đã gửi quá nhiều yêu cầu. Vui lòng đợi một lúc rồi thử lại.",
                "submitted": False,
                "dev_reset_link": None,
            },
            status_code=429,
        )
    if not_robot != "yes" or not captcha_is_valid(captcha_token, captcha_answer):
        fresh_challenge, fresh_token = new_captcha()
        return templates.TemplateResponse(
            "forgot_password.html",
            {
                "request": request,
                "captcha_challenge": fresh_challenge,
                "captcha_token": fresh_token,
                "error": "Xác minh trực quan chưa đúng. Vui lòng thử lại.",
                "submitted": False,
                "dev_reset_link": None,
            },
            status_code=400,
        )

    account = db.scalar(select(User).where(User.email == normalized_email))
    dev_reset_link = None
    allow_local_link = development_reset_links_enabled(request)
    smtp_configured = bool(os.getenv("SMTP_HOST"))
    base_url = public_base_url(request)
    if account and (smtp_configured or allow_local_link) and base_url:
        nonce = secrets.token_urlsafe(32)
        account.reset_token_hash = hashlib.sha256(nonce.encode()).hexdigest()
        account.reset_token_expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=RESET_TOKEN_TTL_SECONDS)
        ).isoformat()
        db.commit()
        token = reset_signer.dumps({"uid": account.id, "nonce": nonce})
        reset_url = f"{base_url}/reset-password/{token}"
        email_sent = False
        if smtp_configured:
            try:
                email_sent = send_password_reset_email(account.email, reset_url)
                if email_sent:
                    logger.info(
                        "Password-reset email accepted by SMTP for %s", account.email
                    )
            except (OSError, smtplib.SMTPException, ValueError) as exc:
                email_sent = False
                logger.exception(
                    "Could not send password-reset email to %s: %s", account.email, exc
                )
        if allow_local_link and not email_sent:
            dev_reset_link = reset_url
    elif account and smtp_configured and not base_url:
        logger.error(
            "Password reset skipped because no public server URL is configured"
        )

    fresh_challenge, fresh_token = new_captcha()
    return templates.TemplateResponse(
        "forgot_password.html",
        {
            "request": request,
            "captcha_challenge": fresh_challenge,
            "captcha_token": fresh_token,
            "error": None,
            "submitted": True,
            "dev_reset_link": dev_reset_link,
        },
    )

@router.get("/reset-password/{token}", response_class=HTMLResponse)
def reset_password_page(
    token: str, request: Request, db: Session = Depends(db_session)
):
    account = reset_account_for_token(token, db)
    return templates.TemplateResponse(
        "reset_password.html",
        {
            "request": request,
            "token": token,
            "valid": account is not None,
            "error": None,
            "success": False,
        },
        status_code=200 if account else 400,
    )

@router.post("/reset-password/{token}", response_class=HTMLResponse)
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
        error = (
            "Liên kết đặt lại mật khẩu không hợp lệ, đã hết hạn hoặc đã được sử dụng."
        )
    elif len(password) < MIN_PASSWORD_LENGTH:
        error = f"Mật khẩu mới phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự."
    elif password != password_confirm:
        error = "Hai lần nhập mật khẩu không khớp."
    if error:
        return templates.TemplateResponse(
            "reset_password.html",
            {
                "request": request,
                "token": token,
                "valid": account is not None,
                "error": error,
                "success": False,
            },
            status_code=400,
        )

    account.password_hash = pwd.hash(password)
    account.session_version += 1
    account.reset_token_hash = None
    account.reset_token_expires_at = None
    db.commit()
    return templates.TemplateResponse(
        "reset_password.html",
        {
            "request": request,
            "token": token,
            "valid": False,
            "error": None,
            "success": True,
        },
    )

@router.get("/logout")
def logout():
    res = RedirectResponse("/", 303)
    res.delete_cookie("session")
    return res

@router.get("/account/email-change", response_class=HTMLResponse)
def email_change_page(
    request: Request,
    project_id: Optional[int] = None,
    user: User = Depends(current_user),
):
    return templates.TemplateResponse(
        "email_change.html",
        {
            "request": request,
            "mode": "start",
            "user": user,
            "target": user,
            "project_id": project_id,
            "error": None,
            "back_path": email_change_back_path(user, project_id),
        },
    )

@router.post("/account/email-change/prepare", response_class=HTMLResponse)
def prepare_email_change(
    request: Request,
    email: str = Form(...),
    current_password: str = Form(""),
    account_id: str = Form(""),
    project_id: Optional[int] = Form(None),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    target = email_change_target(account_id, user, db)
    new_email = bounded_text(email.lower(), "Email mới", 255)
    back_path = email_change_back_path(user, project_id)
    context = {
        "request": request,
        "mode": "start",
        "user": user,
        "target": target,
        "project_id": project_id,
        "error": None,
        "back_path": back_path,
    }
    if "@" not in new_email:
        context["error"] = "Email mới không hợp lệ."
        return templates.TemplateResponse("email_change.html", context, status_code=400)
    if new_email == target.email.lower().strip():
        context["error"] = "Email mới phải khác email hiện tại."
        return templates.TemplateResponse("email_change.html", context, status_code=400)
    if target.id == user.id and (
        not current_password or not pwd.verify(current_password, target.password_hash)
    ):
        context["error"] = "Vui lòng nhập đúng mật khẩu hiện tại trước khi đổi email."
        return templates.TemplateResponse("email_change.html", context, status_code=400)
    if (
        db.scalar(
            select(User.id).where(
                func.lower(User.email) == new_email, User.id != target.id
            )
        )
        is not None
    ):
        context["error"] = "Email mới đã được sử dụng bởi tài khoản khác."
        return templates.TemplateResponse("email_change.html", context, status_code=409)
    confirmation_token = email_change_signer.dumps(
        {
            "actor_id": user.id,
            "account_id": target.id,
            "new_email": new_email,
            "project_id": project_id,
        }
    )
    return templates.TemplateResponse(
        "email_change.html",
        {
            "request": request,
            "mode": "confirm",
            "user": user,
            "target": target,
            "new_email": new_email,
            "confirmation_token": confirmation_token,
            "back_path": back_path,
            "error": None,
        },
    )

@router.post("/account/email-change/confirm", response_class=HTMLResponse)
def confirm_email_change(
    request: Request,
    confirmation_token: str = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    target, new_email, project_id = email_change_confirmation_data(
        confirmation_token, user, db
    )
    back_path = email_change_back_path(user, project_id)
    if (
        db.scalar(
            select(User.id).where(
                func.lower(User.email) == new_email, User.id != target.id
            )
        )
        is not None
    ):
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "confirm",
                "user": user,
                "target": target,
                "new_email": new_email,
                "confirmation_token": confirmation_token,
                "back_path": back_path,
                "error": "Email mới vừa được tài khoản khác sử dụng.",
            },
            status_code=409,
        )
    if rate_limit_exceeded(
        "email_change_actor", str(user.id), limit=5, window_seconds=15 * 60
    ) or rate_limit_exceeded(
        "email_change_target", new_email, limit=5, window_seconds=15 * 60
    ):
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "confirm",
                "user": user,
                "target": target,
                "new_email": new_email,
                "confirmation_token": confirmation_token,
                "back_path": back_path,
                "error": "Bạn đã yêu cầu đổi email quá nhiều lần. Vui lòng thử lại sau.",
            },
            status_code=429,
        )
    otp = f"{secrets.randbelow(1_000_000):06d}"
    try:
        if not send_email_change_otp_email(new_email, otp):
            raise RuntimeError("SMTP chưa được cấu hình")
    except (OSError, smtplib.SMTPException, RuntimeError, ValueError) as exc:
        logger.exception("Could not send email-change OTP to %s: %s", new_email, exc)
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "confirm",
                "user": user,
                "target": target,
                "new_email": new_email,
                "confirmation_token": confirmation_token,
                "back_path": back_path,
                "error": "Chưa thể gửi OTP tới email mới. Vui lòng thử lại sau.",
            },
            status_code=503,
        )
    old = db.scalar(
        select(EmailChangeVerification)
        .where(EmailChangeVerification.user_id == target.id)
        .with_for_update()
    )
    if old:
        db.delete(old)
        db.flush()
    nonce = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    verification = EmailChangeVerification(
        user_id=target.id,
        requested_by_user_id=user.id,
        new_email=new_email,
        otp_hash=email_change_otp_hash(target.id, new_email, otp),
        token_hash=hashlib.sha256(nonce.encode()).hexdigest(),
        expires_at=(now + timedelta(seconds=EMAIL_CHANGE_OTP_TTL_SECONDS)).isoformat(),
        attempt_count=0,
    )
    db.add(verification)
    db.commit()
    verification_token = email_change_otp_signer.dumps(
        {"id": verification.id, "nonce": nonce}
    )
    return templates.TemplateResponse(
        "email_change.html",
        {
            "request": request,
            "mode": "otp",
            "user": user,
            "target": target,
            "masked_email": mask_email(new_email),
            "verification_token": verification_token,
            "back_path": back_path,
            "error": None,
        },
    )

@router.post("/account/email-change/verify", response_class=HTMLResponse)
def verify_email_change(
    request: Request,
    verification_token: str = Form(...),
    otp: str = Form(...),
    user: User = Depends(current_user),
    db: Session = Depends(db_session),
):
    verification = email_change_verification_for_token(verification_token, user, db)
    if not verification:
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "expired",
                "user": user,
                "back_path": email_change_back_path(user),
                "error": "Phiên xác minh email không hợp lệ hoặc đã hết hạn.",
            },
            status_code=400,
        )
    target = db.get(User, verification.user_id)
    if not target or (
        target.id != user.id and not admin_can_manage_account(user, target, db)
    ):
        raise HTTPException(403, "Bạn không còn quyền đổi email tài khoản này")
    now = datetime.now(timezone.utc)
    if datetime.fromisoformat(verification.expires_at) <= now:
        db.delete(verification)
        db.commit()
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "expired",
                "user": user,
                "back_path": email_change_back_path(user),
                "error": "Mã OTP đã hết hạn. Hãy bắt đầu lại thao tác đổi email.",
            },
            status_code=400,
        )
    if verification.attempt_count >= EMAIL_CHANGE_OTP_MAX_ATTEMPTS:
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "expired",
                "user": user,
                "back_path": email_change_back_path(user),
                "error": "Bạn đã nhập sai quá số lần cho phép. Hãy bắt đầu lại thao tác đổi email.",
            },
            status_code=429,
        )
    normalized_otp = otp.strip()
    if (
        not normalized_otp.isdigit()
        or len(normalized_otp) != 6
        or not hmac.compare_digest(
            verification.otp_hash,
            email_change_otp_hash(target.id, verification.new_email, normalized_otp),
        )
    ):
        verification.attempt_count += 1
        remaining = max(0, EMAIL_CHANGE_OTP_MAX_ATTEMPTS - verification.attempt_count)
        db.commit()
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "otp",
                "user": user,
                "target": target,
                "masked_email": mask_email(verification.new_email),
                "verification_token": verification_token,
                "back_path": email_change_back_path(user),
                "error": f"Mã OTP không đúng. Bạn còn {remaining} lần thử.",
            },
            status_code=400,
        )
    if (
        db.scalar(
            select(User.id).where(
                func.lower(User.email) == verification.new_email, User.id != target.id
            )
        )
        is not None
    ):
        return templates.TemplateResponse(
            "email_change.html",
            {
                "request": request,
                "mode": "expired",
                "user": user,
                "back_path": email_change_back_path(user),
                "error": "Email mới vừa được tài khoản khác sử dụng. Hãy chọn email khác.",
            },
            status_code=409,
        )
    target.email = verification.new_email
    target.session_version += 1
    db.delete(verification)
    db.commit()
    response = templates.TemplateResponse(
        "email_change.html",
        {
            "request": request,
            "mode": "success",
            "user": target if target.id == user.id else user,
            "target": target,
            "back_path": email_change_back_path(user),
            "error": None,
        },
    )
    if target.id == user.id:
        set_session_cookie(response, target)
    return response

