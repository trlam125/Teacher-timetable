# Smart TKB Android (WebView)

Project Android này là lớp vỏ WebView cho website Smart TKB. Backend FastAPI và PostgreSQL vẫn chạy trên server; APK không chứa dữ liệu thời khóa biểu.

## Cấu hình URL

Khi build, APK vẫn cần `APP_BASE_URL` làm **URL bootstrap** để biết nơi lấy cấu hình động. Gradle đọc biến này theo thứ tự:

1. File `.env` ở thư mục gốc project.
2. Biến môi trường `APP_BASE_URL`.

Ví dụ trong `.env`:

```env
APP_BASE_URL=https://your-domain.example.com
```

`APP_BASE_URL` phải là HTTPS. Sau khi APK đã được cài, super admin có thể vào **Quản lý tài khoản → URL cho APK** để đổi URL website mà APK mở. APK lưu URL gần nhất để mở nhanh, đồng thời kiểm tra lại `/api/mobile/config` từ URL bootstrap mỗi lần khởi động. Để trống cấu hình quản lý sẽ đưa APK về `APP_BASE_URL`.

Chỉ cần build lại APK nếu chính URL bootstrap `APP_BASE_URL` không còn truy cập được nữa.

## Build APK debug

Yêu cầu JDK 17 trở lên và Android SDK 35. Project đã có Gradle Wrapper nên không cần cài Gradle riêng.

Từ thư mục `android-webview`, chạy:

```powershell
.\gradlew.bat assembleDebug
```

APK được tạo tại:

```text
app/build/outputs/apk/debug/app-debug.apk
```

## Các chức năng lớp Android

- Mở website từ URL quản lý; fallback về `BuildConfig.APP_BASE_URL`.
- Tự kiểm tra cấu hình URL mới từ endpoint bootstrap khi khởi động.
- Giữ cookie đăng nhập WebView.
- JavaScript và local storage cho giao diện hiện tại.
- Điều hướng Back bằng nút hệ thống Android.
- Kéo-thả bằng cảm ứng qua `android-touch-drag.js`.
- Thông báo khi mất mạng hoặc máy chủ ngừng hoạt động.
- Tải file xuất từ website vào thư mục Downloads, kèm cookie phiên đăng nhập.
