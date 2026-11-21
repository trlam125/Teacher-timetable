"""Bound and normalize avatar uploads before storing them in PostgreSQL."""
import io
import secrets
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_AVATAR_BYTES = 5 * 1024 * 1024
MAX_AVATAR_PIXELS = 16_000_000


def normalize_avatar_image(data: bytes) -> bytes:
    if not data or len(data) > MAX_AVATAR_BYTES:
        raise ValueError("Hãy chọn ảnh đại diện có dung lượng tối đa 5 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=["JPEG", "PNG", "WEBP"]) as image:
                if image.width * image.height > MAX_AVATAR_PIXELS:
                    raise ValueError("Ảnh vượt quá 16 triệu điểm ảnh. Hãy chọn ảnh có kích thước nhỏ hơn.")
                image.verify()
            with Image.open(io.BytesIO(data), formats=["JPEG", "PNG", "WEBP"]) as image:
                image = ImageOps.exif_transpose(image).convert("RGBA")
                image.thumbnail((512, 512), Image.Resampling.LANCZOS)
                # A fresh image omits EXIF and other uploaded metadata.
                clean_image = Image.new("RGBA", image.size)
                clean_image.paste(image)
                output = io.BytesIO()
                clean_image.save(output, format="PNG")
                return output.getvalue()
    except (UnidentifiedImageError, OSError, SyntaxError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError("Không đọc được ảnh này. Hãy chọn ảnh PNG, JPG hoặc WebP.") from None


def prepare_avatar_change(upload, remove: bool, account_id: int):
    """None keeps the current avatar; a tuple replaces or clears it."""
    if upload is not None and upload.filename:
        if remove:
            raise ValueError("Hãy chọn đổi ảnh hoặc xóa ảnh đại diện.")
        data = normalize_avatar_image(upload.file.read(MAX_AVATAR_BYTES + 1))
        return f"/account/avatar/{account_id}?v={secrets.token_hex(8)}", data
    if remove:
        return "", None
    return None
