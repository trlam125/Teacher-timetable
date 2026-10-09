from __future__ import annotations

import html
import json
import os
import smtplib
from app.services.foundation import logger
from email.message import EmailMessage
from urllib import error as urllib_error, request as urllib_request


def _running_on_render() -> bool:
    """Return True when the app is running inside a Render service."""
    render_flag = os.getenv("RENDER", "").strip().lower() in {"1", "true", "yes"}
    render_service_id = bool(os.getenv("RENDER_SERVICE_ID", "").strip())
    render_hostname = bool(os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip())
    return render_flag or render_service_id or render_hostname


def email_delivery_configured() -> bool:
    """Return whether the active email transport is configured for this environment.

    Render uses the private Netlify mail proxy over HTTPS. Every other
    environment keeps the original direct SMTP transport.
    """
    if _running_on_render():
        return bool(
            os.getenv("MAIL_API_URL", "").strip()
            and os.getenv("MAIL_API_SECRET", "").strip()
        )
    return bool(os.getenv("SMTP_HOST", "").strip())


def _send_email_via_mail_proxy(
    recipient: str, subject: str, body: str, html_body: str | None = None
) -> bool:
    """Send email through the private Netlify SMTP proxy over HTTPS."""
    api_url = os.getenv("MAIL_API_URL", "").strip()
    api_secret = os.getenv("MAIL_API_SECRET", "").strip()
    if not api_url or not api_secret:
        logger.error(
            "Netlify mail proxy is not configured. Missing MAIL_API_URL or MAIL_API_SECRET"
        )
        return False

    timeout = max(5, int(os.getenv("EMAIL_HTTP_TIMEOUT_SECONDS", "20")))
    payload_data: dict[str, str] = {
        "to": recipient,
        "subject": subject,
        "text": body,
    }
    if html_body:
        payload_data["html"] = html_body
    payload = json.dumps(
        payload_data,
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib_request.Request(
        api_url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_secret}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Smart-TKB/1.0",
        },
    )

    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            if 200 <= response.status < 300:
                logger.info("Email sent to %s via Netlify mail proxy", recipient)
                return True
            logger.error(
                "Netlify mail proxy returned HTTP %s for %s: %s",
                response.status,
                recipient,
                response_body,
            )
            return False
    except urllib_error.HTTPError as exc:
        try:
            error_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            error_body = ""
        logger.error(
            "Netlify mail proxy HTTP error %s for %s: %s",
            exc.code,
            recipient,
            error_body,
        )
        return False
    except (urllib_error.URLError, TimeoutError, OSError, ValueError) as exc:
        logger.exception(
            "Could not send email to %s via Netlify mail proxy: %s", recipient, exc
        )
        return False


def _send_email_via_smtp(
    recipient: str, subject: str, body: str, html_body: str | None = None
) -> bool:
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    if not smtp_host:
        logger.error("SMTP_HOST is not configured")
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

    if smtp_host.lower() == "smtp.gmail.com" and (not smtp_user or not smtp_password):
        raise smtplib.SMTPAuthenticationError(
            535, b"Missing SMTP_USER or SMTP_PASSWORD"
        )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = smtp_from
    message["To"] = recipient
    message.set_content(body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

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
            logger.error("SMTP refused recipient(s): %s", list(refused))
            return False
    logger.info("Email sent to %s via SMTP", recipient)
    return True


def send_email_message(
    recipient: str, subject: str, body: str, html_body: str | None = None
) -> bool:
    """Use the Netlify SMTP proxy on Render; use SMTP everywhere else."""
    if _running_on_render():
        return _send_email_via_mail_proxy(recipient, subject, body, html_body=html_body)
    return _send_email_via_smtp(recipient, subject, body, html_body=html_body)


def _render_email_html(title: str, preheader: str, content_html: str) -> str:
    escaped_title = html.escape(title)
    escaped_preheader = html.escape(preheader)
    return (
        '<!DOCTYPE html>\n'
        '<html lang="vi">\n'
        '<head>\n'
        '    <meta charset="utf-8">\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'    <title>{escaped_title}</title>\n'
        '</head>\n'
        '<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased;color:#1e293b;">\n'
        '    <div style="display:none;max-height:0px;overflow:hidden;mso-hide:all;">\n'
        f'        {escaped_preheader}\n'
        '    </div>\n'
        '    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#f1f5f9;padding:36px 16px;">\n'
        '        <tr>\n'
        '            <td align="center">\n'
        '                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:540px;background-color:#ffffff;border-radius:16px;border:1px solid #e2e8f0;box-shadow:0 4px 12px rgba(15,23,42,0.06);overflow:hidden;">\n'
        '                    <!-- Header -->\n'
        '                    <tr>\n'
        '                        <td style="padding:28px 32px;background:linear-gradient(135deg,#1e3a8a 0%,#2563eb 100%);text-align:center;">\n'
        '                            <h1 style="margin:0;font-size:24px;font-weight:800;color:#ffffff;letter-spacing:0.5px;">\n'
        '                                Smart TKB\n'
        '                            </h1>\n'
        '                            <p style="margin:6px 0 0 0;font-size:13px;color:#dbeafe;font-weight:500;">\n'
        '                                Hệ thống quản lý &amp; xếp thời khóa biểu\n'
        '                            </p>\n'
        '                        </td>\n'
        '                    </tr>\n'
        '                    <!-- Main Body -->\n'
        '                    <tr>\n'
        '                        <td style="padding:32px 32px 28px 32px;">\n'
        f'                            {content_html}\n'
        '                        </td>\n'
        '                    </tr>\n'
        '                    <!-- Footer -->\n'
        '                    <tr>\n'
        '                        <td style="padding:20px 32px;background-color:#f8fafc;border-top:1px solid #e2e8f0;text-align:center;">\n'
        '                            <p style="margin:0;font-size:12px;color:#94a3b8;line-height:1.5;">\n'
        '                                Thư này được gửi tự động từ hệ thống Smart TKB.<br>\n'
        '                                Vui lòng không trả lời trực tiếp email này.\n'
        '                            </p>\n'
        '                        </td>\n'
        '                    </tr>\n'
        '                </table>\n'
        '            </td>\n'
        '        </tr>\n'
        '    </table>\n'
        '</body>\n'
        '</html>'
    )


def send_password_reset_email(recipient: str, reset_url: str) -> bool:
    subject = "Đặt lại mật khẩu Smart TKB"
    text_body = (
        "Xin chào,\n\n"
        "Bạn vừa yêu cầu đặt lại mật khẩu cho tài khoản Smart TKB.\n\n"
        "Vui lòng mở liên kết sau trong vòng 30 phút để thiết lập mật khẩu mới:\n\n"
        f"    {reset_url}\n\n"
        "Nếu bạn không yêu cầu đặt lại mật khẩu, vui lòng bỏ qua email này. Mật khẩu của bạn vẫn an toàn."
    )
    safe_url = html.escape(reset_url)
    content_html = f"""
    <p style="margin:0 0 16px 0;font-size:15px;line-height:1.6;color:#334155;">
        Xin chào,
    </p>
    <p style="margin:0 0 20px 0;font-size:15px;line-height:1.6;color:#334155;">
        Bạn vừa yêu cầu đặt lại mật khẩu cho tài khoản tại hệ thống <strong>Smart TKB</strong>. Vui lòng bấm vào nút bên dưới để thiết lập mật khẩu mới:
    </p>
    <div style="margin:28px 0;text-align:center;">
        <a href="{safe_url}" target="_blank" style="display:inline-block;background-color:#2563eb;color:#ffffff;text-decoration:none;font-size:15px;font-weight:600;padding:14px 32px;border-radius:8px;box-shadow:0 4px 6px -1px rgba(37,99,235,0.25);">
            Đặt lại mật khẩu
        </a>
        <div style="margin-top:10px;font-size:12px;color:#64748b;">
            Liên kết có hiệu lực trong vòng <strong>30 phút</strong>
        </div>
    </div>
    <div style="margin-top:24px;padding-top:16px;border-top:1px solid #e2e8f0;">
        <p style="margin:0 0 8px 0;font-size:13px;line-height:1.5;color:#64748b;">
            Nếu nút bấm trên không mở được, bạn hãy sao chép và dán liên kết sau vào trình duyệt:
        </p>
        <div style="background-color:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:10px 14px;word-break:break-all;font-family:'Consolas','Courier New',monospace;font-size:13px;line-height:1.5;color:#2563eb;">
            <a href="{safe_url}" style="color:#2563eb;text-decoration:underline;">{safe_url}</a>
        </div>
    </div>
    <p style="margin:20px 0 0 0;font-size:13px;line-height:1.5;color:#64748b;">
        Nếu bạn không yêu cầu đặt lại mật khẩu, vui lòng bỏ qua email này. Mật khẩu hiện tại của bạn vẫn an toàn.
    </p>
    """
    html_body = _render_email_html(
        subject, "Liên kết đặt lại mật khẩu Smart TKB", content_html
    )
    return send_email_message(recipient, subject, text_body, html_body=html_body)


def send_registration_otp_email(recipient: str, otp: str, teacher_name: str) -> bool:
    subject = "Mã xác nhận đăng ký Smart TKB"
    safe_name = teacher_name.strip() if teacher_name else "bạn"
    text_body = (
        f"Xin chào {safe_name},\n\n"
        "Bạn vừa thực hiện đăng ký tài khoản trên hệ thống Smart TKB.\n\n"
        "Mã OTP xác nhận của bạn là:\n\n"
        f"    {otp}\n\n"
        "Mã có hiệu lực trong vòng 10 phút và chỉ dùng được một lần.\n\n"
        "Nếu bạn không thực hiện đăng ký này, vui lòng bỏ qua email."
    )
    safe_name_html = html.escape(safe_name)
    safe_otp_html = html.escape(otp.strip())
    content_html = f"""
    <p style="margin:0 0 16px 0;font-size:15px;line-height:1.6;color:#334155;">
        Xin chào <strong>{safe_name_html}</strong>,
    </p>
    <p style="margin:0 0 20px 0;font-size:15px;line-height:1.6;color:#334155;">
        Bạn vừa thực hiện đăng ký tài khoản trên hệ thống <strong>Smart TKB</strong>. Vui lòng nhập mã OTP dưới đây để hoàn tất xác thực tài khoản:
    </p>
    <div style="margin:28px 0;text-align:center;">
        <div style="display:inline-block;background-color:#f8fafc;border:2px dashed #94a3b8;border-radius:12px;padding:14px 28px;font-size:32px;font-weight:800;letter-spacing:8px;color:#0f172a;font-family:'Consolas','Courier New',monospace;">
            {safe_otp_html}
        </div>
        <div style="margin-top:10px;font-size:12px;color:#64748b;">
            Mã có hiệu lực trong vòng <strong>10 phút</strong> (dùng 1 lần duy nhất)
        </div>
    </div>
    <p style="margin:24px 0 0 0;font-size:13px;line-height:1.5;color:#64748b;border-top:1px solid #e2e8f0;padding-top:16px;">
        Nếu bạn không thực hiện đăng ký này, bạn có thể an tâm bỏ qua email này.
    </p>
    """
    html_body = _render_email_html(
        subject, f"Mã OTP đăng ký Smart TKB: {otp}", content_html
    )
    return send_email_message(recipient, subject, text_body, html_body=html_body)


def send_email_change_otp_email(recipient: str, otp: str) -> bool:
    subject = "Mã xác nhận đổi email Smart TKB"
    text_body = (
        "Xin chào,\n\n"
        "Bạn vừa yêu cầu thay đổi địa chỉ email trên hệ thống Smart TKB.\n\n"
        "Mã OTP xác nhận email mới của bạn là:\n\n"
        f"    {otp}\n\n"
        "Mã có hiệu lực trong vòng 10 phút và chỉ dùng được một lần.\n\n"
        "Nếu bạn không yêu cầu thay đổi email, vui lòng bỏ qua thư này."
    )
    safe_otp_html = html.escape(otp.strip())
    content_html = f"""
    <p style="margin:0 0 16px 0;font-size:15px;line-height:1.6;color:#334155;">
        Xin chào,
    </p>
    <p style="margin:0 0 20px 0;font-size:15px;line-height:1.6;color:#334155;">
        Bạn vừa yêu cầu thay đổi địa chỉ email cho tài khoản <strong>Smart TKB</strong>. Vui lòng nhập mã OTP dưới đây để xác nhận địa chỉ email mới:
    </p>
    <div style="margin:28px 0;text-align:center;">
        <div style="display:inline-block;background-color:#f8fafc;border:2px dashed #94a3b8;border-radius:12px;padding:14px 28px;font-size:32px;font-weight:800;letter-spacing:8px;color:#0f172a;font-family:'Consolas','Courier New',monospace;">
            {safe_otp_html}
        </div>
        <div style="margin-top:10px;font-size:12px;color:#64748b;">
            Mã có hiệu lực trong vòng <strong>10 phút</strong> (dùng 1 lần duy nhất)
        </div>
    </div>
    <p style="margin:24px 0 0 0;font-size:13px;line-height:1.5;color:#64748b;border-top:1px solid #e2e8f0;padding-top:16px;">
        Nếu bạn không yêu cầu thay đổi email, hãy bỏ qua thư này hoặc liên hệ ngay với quản trị viên để bảo vệ tài khoản.
    </p>
    """
    html_body = _render_email_html(
        subject, f"Mã OTP đổi email Smart TKB: {otp}", content_html
    )
    return send_email_message(recipient, subject, text_body, html_body=html_body)
