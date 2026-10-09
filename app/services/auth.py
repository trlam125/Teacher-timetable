"""Compatibility entry point; implementations live in focused modules."""
from app.services.authentication.credentials import (
    Passwords,
    pwd,
    signer,
    reset_signer,
    captcha_signer,
    registration_signer,
    email_change_signer,
    email_change_otp_signer,
)
from app.services.authentication.captcha import (
    _captcha_svg_data_uri,
    _captcha_puzzle_piece_data_uris,
    new_captcha,
    _consume_captcha_nonce,
    captcha_is_valid,
)
from app.services.authentication.rate_limits import (
    _rate_limit_identity,
    client_rate_limit_key,
    rate_limit_exceeded,
    rate_limit_blocked,
    clear_rate_limit_bucket,
)
from app.services.authentication.mail import (
    _running_on_render,
    email_delivery_configured,
    _send_email_via_mail_proxy,
    _send_email_via_smtp,
    send_email_message,
    _render_email_html,
    send_password_reset_email,
    send_registration_otp_email,
    send_email_change_otp_email,
)
from app.services.authentication.sessions import (
    public_base_url,
    db_session,
    set_session_cookie,
    current_user,
    development_reset_links_enabled,
)
from app.services.authentication.permissions import (
    is_admin,
    is_super_admin,
    user_greeting_name,
    user_school_ids,
    user_schools,
    user_can_access_school,
    admin_can_manage_account,
)
from app.services.authentication.verification import (
    registration_otp_hash,
    email_change_otp_hash,
    mask_email,
    registration_verification_for_token,
    registration_otp_context,
    reset_account_for_token,
    email_change_target,
    email_change_back_path,
    email_change_confirmation_data,
    email_change_verification_for_token,
)

__all__ = [name for name in globals() if not name.startswith('__')]
