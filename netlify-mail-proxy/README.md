# Smart TKB Netlify Mail Proxy

## 1. Netlify

**Project configuration -> Environment variables**

```env
MAIL_API_SECRET=<chuoi-bi-mat-dai>
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-16-character-app-password
SMTP_FROM=your-email@gmail.com
SMTP_SSL=false
SMTP_STARTTLS=true
SMTP_TIMEOUT_SECONDS=30
EMAIL_FROM_NAME=Smart TKB
```

Không đưa secret thật vào `netlify.toml`.

Endpoint gửi mail sau deploy:

```text
https://<ten-site>.netlify.app/api/send-email
```

## 2. Render

```env
MAIL_API_URL=https://<ten-site>.netlify.app/api/send-email
MAIL_API_SECRET=<secret-Netlify>
EMAIL_HTTP_TIMEOUT_SECONDS=20
```

Python:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Dùng đúng cùng một giá trị ở Netlify và Render.
