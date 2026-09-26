from __future__ import annotations

from app.services.foundation import *
from app.services.web import _parse_iso_datetime

class Passwords:
    @staticmethod
    def hash(password: str) -> str:
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), 200_000
        ).hex()
        return f"pbkdf2_sha256${salt}${digest}"

    @staticmethod
    def verify(password: str, encoded: str) -> bool:
        try:
            algo, salt, digest = encoded.split("$", 2)
            if algo != "pbkdf2_sha256":
                return False
            actual = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), salt.encode(), 200_000
            ).hex()
            return hmac.compare_digest(actual, digest)
        except Exception:
            return False

pwd = Passwords()
signer = URLSafeTimedSerializer(SECRET_KEY, salt="session")
reset_signer = URLSafeTimedSerializer(SECRET_KEY, salt="password-reset")
captcha_signer = URLSafeTimedSerializer(SECRET_KEY, salt="forgot-password-captcha")
registration_signer = URLSafeTimedSerializer(
    SECRET_KEY, salt="registration-verification"
)
email_change_signer = URLSafeTimedSerializer(
    SECRET_KEY, salt="email-change-confirmation"
)
email_change_otp_signer = URLSafeTimedSerializer(
    SECRET_KEY, salt="email-change-verification"
)


def _captcha_svg_data_uri(kind: str, variant: int = 0) -> str:
    """Return a small self-contained SVG used by the visual captcha."""
    accents = [
        ("#e0f2fe", "#38bdf8", "#0f172a"),
        ("#ede9fe", "#8b5cf6", "#1e1b4b"),
        ("#dcfce7", "#22c55e", "#14532d"),
        ("#ffedd5", "#fb923c", "#7c2d12"),
        ("#fce7f3", "#ec4899", "#831843"),
    ]
    bg, accent, ink = accents[variant % len(accents)]
    drawings = {
        "tree": f'''<rect x="78" y="58" width="24" height="43" rx="5" fill="#8b5a2b"/>
<circle cx="90" cy="45" r="32" fill="{accent}"/><circle cx="66" cy="56" r="21" fill="{accent}"/><circle cx="113" cy="57" r="22" fill="{accent}"/>''',
        "car": f'''<path d="M42 70h97l-9-27c-2-7-8-11-15-11H70c-7 0-13 4-16 11L42 70Z" fill="{accent}"/>
<rect x="31" y="65" width="118" height="31" rx="13" fill="{accent}"/><circle cx="58" cy="96" r="13" fill="{ink}"/><circle cx="124" cy="96" r="13" fill="{ink}"/><path d="M66 42h43l7 21H58l8-21Z" fill="#fff" opacity=".82"/>''',
        "cloud": f'''<circle cx="72" cy="64" r="26" fill="{accent}"/><circle cx="101" cy="48" r="34" fill="{accent}"/><circle cx="128" cy="68" r="23" fill="{accent}"/><rect x="51" y="63" width="96" height="36" rx="18" fill="{accent}"/>''',
        "house": f'''<path d="M37 58 90 20l53 38v47H37V58Z" fill="{accent}"/><path d="M28 61 90 14l62 47" fill="none" stroke="{ink}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/><rect x="76" y="70" width="28" height="35" rx="3" fill="#fff" opacity=".86"/><rect x="48" y="66" width="21" height="20" rx="3" fill="#fff" opacity=".76"/>''',
        "star": f'''<path d="m90 15 17 34 38 5-28 27 7 38-34-18-34 18 7-38-28-27 38-5 17-34Z" fill="{accent}" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>''',
        "flower": f'''<circle cx="90" cy="55" r="15" fill="#facc15"/><circle cx="90" cy="29" r="21" fill="{accent}"/><circle cx="116" cy="51" r="21" fill="{accent}"/><circle cx="106" cy="80" r="21" fill="{accent}"/><circle cx="74" cy="80" r="21" fill="{accent}"/><circle cx="64" cy="51" r="21" fill="{accent}"/><path d="M90 93v24" stroke="#16a34a" stroke-width="9" stroke-linecap="round"/>''',
    }
    drawing = drawings[kind]
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="180" height="120" viewBox="0 0 180 120">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{bg}"/><stop offset="1" stop-color="#ffffff"/></linearGradient></defs>
<rect width="180" height="120" rx="18" fill="url(#g)"/><circle cx="18" cy="18" r="7" fill="{accent}" opacity=".24"/><circle cx="160" cy="98" r="12" fill="{accent}" opacity=".18"/>{drawing}</svg>'''
    return "data:image/svg+xml;charset=UTF-8," + quote(svg, safe="")

def _captcha_puzzle_piece_data_uris() -> list[str]:
    """Vẽ ảnh raster rồi cắt thật thành 4 mảnh; client không nhận tọa độ gốc."""
    width, height = 360, 240
    rng = random.SystemRandom()
    palette = rng.choice(
        [
            ((219, 234, 254), (147, 197, 253), (34, 197, 94)),
            ((252, 231, 243), (196, 181, 253), (22, 163, 74)),
            ((220, 252, 231), (186, 230, 253), (16, 185, 129)),
        ]
    )
    sky_top, sky_bottom, grass = palette
    image = Image.new("RGB", (width, height), sky_top)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(int(a + (b - a) * ratio) for a, b in zip(sky_top, sky_bottom))
        draw.line((0, y, width, y), fill=color)

    sun_x = rng.randint(260, 310)
    sun_y = rng.randint(38, 62)
    draw.ellipse((sun_x - 28, sun_y - 28, sun_x + 28, sun_y + 28), fill=(250, 204, 21))
    cloud_x = rng.randint(62, 108)
    cloud_y = rng.randint(36, 56)
    for dx, dy, radius in ((-28, 8, 18), (0, 0, 25), (28, 10, 17)):
        draw.ellipse(
            (
                cloud_x + dx - radius,
                cloud_y + dy - radius,
                cloud_x + dx + radius,
                cloud_y + dy + radius,
            ),
            fill=(248, 250, 252),
        )

    draw.polygon(
        [
            (0, 176),
            (82, 92),
            (141, 151),
            (203, 61),
            (295, 171),
            (360, 108),
            (360, 240),
            (0, 240),
        ],
        fill=(100, 116, 139),
    )
    draw.polygon(
        [
            (0, 187),
            (82, 121),
            (143, 179),
            (203, 93),
            (293, 191),
            (360, 135),
            (360, 240),
            (0, 240),
        ],
        fill=grass,
    )

    house_x = rng.randint(76, 105)
    draw.polygon(
        [(house_x - 56, 184), (house_x, 139), (house_x + 58, 184)], fill=(124, 45, 18)
    )
    draw.rectangle((house_x - 48, 184, house_x + 48, 239), fill=(251, 146, 60))
    draw.rectangle((house_x - 13, 200, house_x + 13, 239), fill=(255, 247, 237))
    draw.rectangle((house_x + 22, 195, house_x + 39, 213), fill=(224, 242, 254))

    tree_x = rng.randint(270, 310)
    draw.rounded_rectangle(
        (tree_x - 8, 163, tree_x + 8, 229), radius=5, fill=(146, 64, 14)
    )
    for dx, dy, radius, color in (
        (0, -18, 38, (21, 128, 61)),
        (-28, -5, 27, (22, 163, 74)),
        (28, -4, 28, (34, 197, 94)),
    ):
        draw.ellipse(
            (
                tree_x + dx - radius,
                163 + dy - radius,
                tree_x + dx + radius,
                163 + dy + radius,
            ),
            fill=color,
        )

    for _ in range(18):
        x = rng.randint(8, width - 8)
        y = rng.randint(8, height - 8)
        r = rng.randint(2, 5)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255))

    pieces: list[str] = []
    for top in (0, height // 2):
        for left in (0, width // 2):
            crop = image.crop((left, top, left + width // 2, top + height // 2))
            buffer = io.BytesIO()
            crop.save(buffer, format="PNG", optimize=True)
            pieces.append(
                "data:image/png;base64,"
                + base64.b64encode(buffer.getvalue()).decode("ascii")
            )
    return pieces

def new_captcha(purpose: str = "password_reset") -> tuple[dict, str]:
    kind = "images" if secrets.randbelow(100) < 65 else "puzzle"
    issued_at = int(datetime.now(timezone.utc).timestamp())
    nonce = secrets.token_urlsafe(18)

    if kind == "images":
        labels = {
            "tree": "cây",
            "car": "ô tô",
            "cloud": "đám mây",
            "house": "ngôi nhà",
            "star": "ngôi sao",
            "flower": "bông hoa",
        }
        categories = list(labels)
        target = secrets.choice(categories)
        system_random = random.SystemRandom()
        distractors = [item for item in categories if item != target]
        tile_kinds = [target, target] + system_random.sample(distractors, 4)
        system_random.shuffle(tile_kinds)
        tiles = []
        correct_ids = []
        for index, tile_kind in enumerate(tile_kinds):
            tile_id = secrets.token_urlsafe(6)
            if tile_kind == target:
                correct_ids.append(tile_id)
            tiles.append(
                {
                    "id": tile_id,
                    "src": _captcha_svg_data_uri(tile_kind, secrets.randbelow(5)),
                    "alt": f"Hình xác minh {index + 1}",
                }
            )
        expected = ",".join(sorted(correct_ids))
        challenge = {
            "kind": "images",
            "prompt": f"Chọn tất cả hình có {labels[target]}",
            "tiles": tiles,
            "required_count": len(correct_ids),
        }
    else:
        piece_images = _captcha_puzzle_piece_data_uris()
        pieces = []
        correct_ids = []
        for index, piece_image in enumerate(piece_images):
            piece_id = secrets.token_urlsafe(6)
            correct_ids.append(piece_id)
            pieces.append({"id": piece_id, "src": piece_image})
        random.SystemRandom().shuffle(pieces)
        while [piece["id"] for piece in pieces] == correct_ids:
            random.SystemRandom().shuffle(pieces)
        expected = ",".join(correct_ids)
        challenge = {
            "kind": "puzzle",
            "prompt": "Ghép 4 mảnh thành một bức tranh hoàn chỉnh",
            "pieces": pieces,
        }

    answer_hash = hmac.new(
        SECRET_KEY.encode(),
        f"captcha:{purpose}:{nonce}:{expected}".encode(),
        hashlib.sha256,
    ).hexdigest()
    token = captcha_signer.dumps(
        {
            "answer_hash": answer_hash,
            "purpose": purpose,
            "issued_at": issued_at,
            "nonce": nonce,
            "kind": kind,
        }
    )
    return challenge, token

def _consume_captcha_nonce(nonce: str, purpose: str, now_epoch: int) -> bool:
    nonce_hash = hashlib.sha256(nonce.encode()).hexdigest()
    with engine.begin() as connection:
        inserted = connection.exec_driver_sql(
            "INSERT INTO captcha_uses (nonce_hash, purpose, used_at) VALUES (%s, %s, %s) "
            "ON CONFLICT (nonce_hash) DO NOTHING RETURNING nonce_hash",
            (nonce_hash, purpose, now_epoch),
        ).scalar()
        if secrets.randbelow(100) < 5:
            connection.exec_driver_sql(
                "DELETE FROM captcha_uses WHERE used_at < %s",
                (now_epoch - 15 * 60,),
            )
    return inserted is not None

def captcha_is_valid(token: str, answer: str, purpose: str = "password_reset") -> bool:
    try:
        data = captcha_signer.loads(token, max_age=5 * 60)
        now_epoch = int(datetime.now(timezone.utc).timestamp())
        age = now_epoch - int(data["issued_at"])
        submitted = answer.strip()
        if data.get("kind") == "images":
            submitted = ",".join(sorted(filter(None, submitted.split(","))))
        elif data.get("kind") == "puzzle":
            submitted = ",".join(filter(None, submitted.split(",")))
        else:
            return False
        if data["purpose"] != purpose or not 2 <= age <= 5 * 60:
            return False
        submitted_hash = hmac.new(
            SECRET_KEY.encode(),
            f"captcha:{purpose}:{data['nonce']}:{submitted}".encode(),
            hashlib.sha256,
        ).hexdigest()
        if not _consume_captcha_nonce(str(data["nonce"]), purpose, now_epoch):
            return False
        return hmac.compare_digest(str(data["answer_hash"]), submitted_hash)
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return False

def _rate_limit_identity(value: str) -> str:
    return hmac.new(SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()[
        :48
    ]

def client_rate_limit_key(request: Request) -> str:
    host = request.client.host if request.client and request.client.host else "unknown"
    return _rate_limit_identity(host.strip().lower())

def rate_limit_exceeded(
    scope: str, identity: str, *, limit: int, window_seconds: int
) -> bool:
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    cutoff = now_epoch - window_seconds
    bucket_key = f"{scope}:{_rate_limit_identity(identity.strip().lower())}"
    with engine.begin() as connection:
        row = connection.exec_driver_sql(
            "INSERT INTO rate_limit_buckets (bucket_key, window_started_at, count, touched_at) "
            "VALUES (%s, %s, 1, %s) "
            "ON CONFLICT (bucket_key) DO UPDATE SET "
            "count=CASE WHEN rate_limit_buckets.window_started_at < %s THEN 1 ELSE rate_limit_buckets.count + 1 END, "
            "window_started_at=CASE WHEN rate_limit_buckets.window_started_at < %s THEN %s ELSE rate_limit_buckets.window_started_at END, "
            "touched_at=%s "
            "RETURNING count",
            (bucket_key, now_epoch, now_epoch, cutoff, cutoff, now_epoch, now_epoch),
        ).scalar_one()
        if secrets.randbelow(100) < 3:
            connection.exec_driver_sql(
                "DELETE FROM rate_limit_buckets WHERE touched_at < %s",
                (now_epoch - 24 * 60 * 60,),
            )
    return int(row) > limit

def rate_limit_blocked(
    scope: str, identity: str, *, limit: int, window_seconds: int
) -> bool:
    """Kiểm tra bucket hiện tại mà không tăng bộ đếm."""
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    cutoff = now_epoch - window_seconds
    bucket_key = f"{scope}:{_rate_limit_identity(identity.strip().lower())}"
    with engine.begin() as connection:
        row = (
            connection.exec_driver_sql(
                "SELECT window_started_at, count FROM rate_limit_buckets WHERE bucket_key=%s",
                (bucket_key,),
            )
            .mappings()
            .first()
        )
    if not row or int(row["window_started_at"]) < cutoff:
        return False
    return int(row["count"]) >= limit

def clear_rate_limit_bucket(scope: str, identity: str) -> None:
    bucket_key = f"{scope}:{_rate_limit_identity(identity.strip().lower())}"
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DELETE FROM rate_limit_buckets WHERE bucket_key=%s",
            (bucket_key,),
        )

def send_email_message(recipient: str, subject: str, body: str) -> bool:
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    if not smtp_host:
        return False

    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "no-reply@smart-tkb.local").strip()
    use_ssl = os.getenv("SMTP_SSL", "false").strip().lower() in {"1", "true", "yes"}
    use_starttls = os.getenv("SMTP_STARTTLS", "true").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    timeout = max(5, int(os.getenv("SMTP_TIMEOUT_SECONDS", "30")))

    # Gmail SMTP always requires authentication. A missing credential should fail loudly
    # in the server log instead of silently pretending that the message was sent.
    if smtp_host.lower() == "smtp.gmail.com" and (not smtp_user or not smtp_password):
        raise smtplib.SMTPAuthenticationError(
            535, b"Missing SMTP_USER or SMTP_PASSWORD"
        )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = smtp_from
    message["To"] = recipient
    message.set_content(body)

    smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with smtp_class(smtp_host, smtp_port, timeout=timeout) as client:
        client.ehlo()
        if not use_ssl and use_starttls:
            client.starttls()
            client.ehlo()
        if smtp_user:
            client.login(smtp_user, smtp_password)
        refused = client.send_message(message)
        if refused:
            logger.error("SMTP refused password-reset recipient(s): %s", list(refused))
            return False
    return True

def send_password_reset_email(recipient: str, reset_url: str) -> bool:
    return send_email_message(
        recipient,
        "Đặt lại mật khẩu Smart TKB",
        "Bạn vừa yêu cầu đặt lại mật khẩu Smart TKB.\n\n"
        f"Mở liên kết sau trong vòng 30 phút:\n{reset_url}\n\n"
        "Nếu bạn không yêu cầu, hãy bỏ qua email này.",
    )

def send_registration_otp_email(recipient: str, otp: str, teacher_name: str) -> bool:
    return send_email_message(
        recipient,
        "Mã xác nhận đăng ký Smart TKB",
        f"Mã OTP đăng ký tài khoản của bạn là: {otp}\n\n"
        f"Tên giáo viên: {teacher_name}\n"
        "Mã có hiệu lực trong 10 phút và chỉ dùng được một lần.\n\n"
        "Nếu bạn không thực hiện đăng ký này, hãy bỏ qua email.",
    )

def registration_otp_hash(email: str, otp: str) -> str:
    return hmac.new(
        SECRET_KEY.encode(), f"{email}:{otp}".encode(), hashlib.sha256
    ).hexdigest()

def send_email_change_otp_email(recipient: str, otp: str) -> bool:
    return send_email_message(
        recipient,
        "Mã xác nhận đổi email Smart TKB",
        f"Mã OTP xác nhận email mới của bạn là: {otp}\n\n"
        "Mã có hiệu lực trong 10 phút và chỉ dùng được một lần.\n\n"
        "Nếu bạn không yêu cầu thay đổi email, hãy bỏ qua thư này.",
    )

def email_change_otp_hash(user_id: int, email: str, otp: str) -> str:
    value = f"email-change:{user_id}:{email.lower().strip()}:{otp}"
    return hmac.new(SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()

def public_base_url(request: Request) -> str | None:
    if APP_BASE_URL:
        return APP_BASE_URL
    if development_reset_links_enabled(request):
        return str(request.base_url).rstrip("/")
    return None

def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def set_session_cookie(response, user: User):
    response.set_cookie(
        "session",
        signer.dumps({"uid": user.id, "sv": user.session_version}),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=APP_ENV == "production" or APP_BASE_URL.lower().startswith("https://"),
    )

def current_user(request: Request, db: Session = Depends(db_session)) -> User:
    raw = request.cookies.get("session")
    if not raw:
        raise HTTPException(401)
    try:
        data = signer.loads(raw, max_age=SESSION_TTL_SECONDS)
        user = db.get(User, int(data["uid"]))
        if not user or int(data.get("sv", -1)) != user.session_version:
            raise HTTPException(401)
        now = datetime.now(timezone.utc)
        previous = _parse_iso_datetime(user.last_seen)
        if previous is None or (now - previous).total_seconds() >= 60:
            user.last_seen = now.isoformat(timespec="seconds")
            db.commit()
        return user
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        raise HTTPException(401)

def is_admin(user: User) -> bool:
    return user.role in ADMIN_ROLES

def is_super_admin(user: User) -> bool:
    return user.role == "super_admin"

def user_greeting_name(user: User) -> str:
    # Lời chào dùng đúng họ tên/tên hiển thị lưu trong hồ sơ người dùng.
    # Không suy ra tên từ phần trước dấu @ của email vì đó chỉ là tên tài khoản.
    return (user.name or "").strip() or "Người dùng"

def user_school_ids(user: User, db: Session) -> set[int]:
    if is_super_admin(user):
        return set(db.scalars(select(School.id)).all())
    return set(
        db.scalars(
            select(UserSchool.school_id).where(UserSchool.user_id == user.id)
        ).all()
    )

def user_schools(user: User, db: Session) -> list[School]:
    if is_super_admin(user):
        return db.scalars(select(School).order_by(School.name.asc())).all()
    ids = user_school_ids(user, db)
    if not ids:
        return []
    return db.scalars(
        select(School).where(School.id.in_(ids)).order_by(School.name.asc())
    ).all()

def user_can_access_school(user: User, school_id: int | None, db: Session) -> bool:
    if is_super_admin(user):
        return True
    if school_id is None:
        return False
    return school_id in user_school_ids(user, db)

def admin_can_manage_account(
    admin: User, account: User, db: Session | None = None
) -> bool:
    if not is_admin(admin):
        return False
    if account.id == admin.id:
        return True
    if is_super_admin(admin):
        return account.role != "super_admin"
    if account.role != "teacher" or db is None:
        return False

    admin_school_ids = user_school_ids(admin, db)
    if not admin_school_ids:
        return False
    account_school_ids = set(
        db.scalars(
            select(UserSchool.school_id).where(UserSchool.user_id == account.id)
        ).all()
    )
    # Giáo viên chưa có trường có thể được một admin có trường nhận vào phạm vi
    # quản lý; giáo viên đã có trường chỉ hiện cho admin có ít nhất một trường chung.
    return not account_school_ids or bool(admin_school_ids & account_school_ids)

def development_reset_links_enabled(request: Request) -> bool:
    host = (request.url.hostname or "").lower()
    return APP_ENV == "development" and host in {"localhost", "127.0.0.1", "::1"}

def mask_email(email: str) -> str:
    local, separator, domain = email.partition("@")
    if not separator:
        return "***"
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}{'*' * max(2, len(local) - len(visible))}@{domain}"

def registration_verification_for_token(
    token: str,
    db: Session,
    *,
    lock: bool = False,
) -> RegistrationVerification | None:
    try:
        data = registration_signer.loads(token, max_age=REGISTRATION_OTP_TTL_SECONDS)
        query = select(RegistrationVerification).where(
            RegistrationVerification.id == int(data["id"])
        )
        if lock:
            query = query.with_for_update()
        verification = db.scalar(query)
        nonce_hash = hashlib.sha256(str(data["nonce"]).encode()).hexdigest()
        if not verification or not hmac.compare_digest(
            verification.token_hash, nonce_hash
        ):
            return None
        return verification
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return None

def registration_otp_context(
    request: Request,
    verification: RegistrationVerification | None,
    verification_token: str,
    error: str | None = None,
):
    captcha_challenge, captcha_token = new_captcha("registration_resend")
    return {
        "request": request,
        "mode": "register_otp",
        "error": error,
        "verification_token": verification_token,
        "masked_email": mask_email(verification.email)
        if verification
        else "email của bạn",
        "target_teacher_name": verification.name if verification else None,
        "captcha_challenge": captcha_challenge,
        "captcha_token": captcha_token,
    }

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

def email_change_target(account_id: str, actor: User, db: Session) -> User:
    raw = str(account_id or "").strip()
    if not raw:
        return actor
    try:
        target_id = int(raw)
    except ValueError as exc:
        raise HTTPException(400, "Tài khoản cần đổi email không hợp lệ") from exc
    target = db.get(User, target_id)
    if not target or not admin_can_manage_account(actor, target, db):
        raise HTTPException(404, "Không tìm thấy tài khoản trong phạm vi quản lý")
    return target

def email_change_back_path(actor: User, project_id: Optional[int] = None) -> str:
    if actor.role == "teacher":
        return (
            f"/teacher/account?project_id={project_id}"
            if project_id is not None
            else "/teacher/account"
        )
    return "/admin/users"

def email_change_confirmation_data(
    token: str, actor: User, db: Session
) -> tuple[User, str, Optional[int]]:
    try:
        data = email_change_signer.loads(
            token, max_age=EMAIL_CHANGE_CONFIRM_TTL_SECONDS
        )
        if int(data["actor_id"]) != actor.id:
            raise HTTPException(
                403, "Phiên xác nhận đổi email không thuộc tài khoản này"
            )
        target = db.get(User, int(data["account_id"]))
        if not target:
            raise HTTPException(404, "Tài khoản không còn tồn tại")
        if target.id != actor.id and not admin_can_manage_account(actor, target, db):
            raise HTTPException(403, "Bạn không còn quyền đổi email tài khoản này")
        new_email = str(data["new_email"]).lower().strip()
        project_id = data.get("project_id")
        return target, new_email, int(project_id) if project_id is not None else None
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            400, "Phiên xác nhận đổi email không hợp lệ hoặc đã hết hạn"
        ) from exc

def email_change_verification_for_token(
    token: str, actor: User, db: Session
) -> EmailChangeVerification | None:
    try:
        data = email_change_otp_signer.loads(
            token, max_age=EMAIL_CHANGE_OTP_TTL_SECONDS
        )
        row = db.scalar(
            select(EmailChangeVerification)
            .where(EmailChangeVerification.id == int(data["id"]))
            .with_for_update()
        )
        if not row or row.requested_by_user_id != actor.id:
            return None
        nonce_hash = hashlib.sha256(str(data["nonce"]).encode()).hexdigest()
        if not hmac.compare_digest(row.token_hash, nonce_hash):
            return None
        return row
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return None


__all__ = [name for name in globals() if not name.startswith('__')]
