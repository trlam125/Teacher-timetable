from __future__ import annotations

import base64
import hashlib
import hmac
import io
import random
import secrets
from PIL import Image, ImageDraw
from app.config import SECRET_KEY
from app.database import engine
from app.services.authentication.credentials import captcha_signer
from datetime import datetime, timezone
from itsdangerous import BadSignature, SignatureExpired
from urllib.parse import quote


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
        required_count = secrets.randbelow(4) + 1
        tile_kinds = [target] * required_count + system_random.sample(
            distractors, 6 - required_count
        )
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
