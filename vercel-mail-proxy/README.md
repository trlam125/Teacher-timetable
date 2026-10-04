# Smart TKB Vercel Mail Proxy

Proxy mail nhỏ chạy trên Vercel Node.js Function. Render gọi proxy bằng HTTPS; proxy mới kết nối Gmail SMTP qua cổng 587.

## Biến môi trường trên Vercel

- `MAIL_API_SECRET`: chuỗi bí mật dài, phải giống giá trị trên Render.
- `SMTP_HOST=smtp.gmail.com`
- `SMTP_PORT=587`
- `SMTP_USER`: Gmail gửi OTP.
- `SMTP_PASSWORD`: Google App Password 16 ký tự, không phải mật khẩu Gmail.
- `SMTP_FROM`: thường giống `SMTP_USER`.
- `SMTP_SSL=false`
- `SMTP_STARTTLS=true`
- `SMTP_TIMEOUT_SECONDS=30`
- `EMAIL_FROM_NAME=Smart TKB`

## Deploy

1. Trên Vercel tạo project từ cùng GitHub repository.
2. Trong Project Settings -> Build and Deployment, đặt **Root Directory** là `vercel-mail-proxy`.
3. Thêm các Environment Variables ở trên cho Production.
4. Deploy.
5. Endpoint sẽ là `https://<ten-project>.vercel.app/api/send-email`.
6. Trên Render đặt:
   - `MAIL_API_URL=https://<ten-project>.vercel.app/api/send-email`
   - `MAIL_API_SECRET=<cùng secret trên Vercel>`
   - `EMAIL_HTTP_TIMEOUT_SECONDS=20`
7. Render chỉ cần `MAIL_API_URL`, `MAIL_API_SECRET` và timeout; không cần cấu hình `SMTP_*` trực tiếp trên Render.

## Tạo MAIL_API_SECRET

Có thể chạy local:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Không commit secret thật vào GitHub.
