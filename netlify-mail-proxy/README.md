# Smart TKB Netlify Mail Proxy

Mail proxy chạy bằng Netlify Function. FastAPI trên Render gọi proxy qua HTTPS; Netlify Function kết nối Gmail SMTP qua cổng 587 để gửi OTP và email đặt lại mật khẩu.

## 1. Biến môi trường trên Netlify

Trong **Project configuration -> Environment variables**, tạo các biến sau:

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

`SMTP_PASSWORD` phải là Google App Password, không phải mật khẩu Gmail thông thường.

Không đưa secret thật vào `.env.example`, GitHub hoặc `netlify.toml`.

## 2. Deploy thư mục này lên Netlify

### Cách dùng GitHub

1. Push toàn bộ repository lên GitHub.
2. Trong Netlify chọn **Add new project -> Import an existing project**.
3. Chọn repository.
4. Đặt **Base directory** là `netlify-mail-proxy`.
5. Netlify sẽ đọc `netlify.toml`; không cần build command riêng.
6. Thêm các Environment variables ở mục 1.
7. Deploy lại site sau khi thêm hoặc sửa biến môi trường.

Endpoint gửi mail sau deploy:

```text
https://<ten-site>.netlify.app/api/send-email
```

Function chỉ chấp nhận `POST` có header:

```text
Authorization: Bearer <MAIL_API_SECRET>
```

và body JSON:

```json
{
  "to": "user@example.com",
  "subject": "Test",
  "text": "Hello"
}
```

## 3. Cấu hình Render

Trên Web Service FastAPI ở Render, đặt:

```env
MAIL_API_URL=https://<ten-site>.netlify.app/api/send-email
MAIL_API_SECRET=<cung-secret-da-dat-tren-Netlify>
EMAIL_HTTP_TIMEOUT_SECONDS=20
```

Render không cần các biến `SMTP_*`; các biến SMTP chỉ cần đặt trên Netlify.

Sau khi đổi biến môi trường, redeploy/restart Render service.

## 4. Tạo MAIL_API_SECRET

Có thể tạo chuỗi ngẫu nhiên bằng Python:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Dùng đúng cùng một giá trị ở Netlify và Render.

## 5. Gmail

Với Gmail:

1. Bật xác minh 2 bước cho tài khoản Google.
2. Tạo App Password.
3. Đặt App Password vào `SMTP_PASSWORD` trên Netlify.
4. Dùng cổng `587`, `SMTP_SSL=false`, `SMTP_STARTTLS=true`.
