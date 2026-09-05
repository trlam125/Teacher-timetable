# Smart TKB Android (WebView)

Project Android này là lớp vỏ WebView cho website Smart TKB. Backend FastAPI và PostgreSQL vẫn chạy trên server; APK không chứa dữ liệu thời khóa biểu.

## URL backend của APK

APK lấy `APP_BASE_URL` tại thời điểm build theo thứ tự ưu tiên:

1. Gradle property `-PAPP_BASE_URL=https://...`
2. Biến môi trường `APP_BASE_URL`
3. `APP_BASE_URL` trong file `.env` ở thư mục gốc repository

Không còn URL server hard-code trong `app/build.gradle.kts`. URL phải dùng HTTPS và không cần dấu `/` ở cuối.

Build debug thông thường (nếu `.env` đã có `APP_BASE_URL`):

```powershell
.\gradlew.bat assembleDebug
```

Hoặc override trực tiếp:

```powershell
.\gradlew.bat assembleDebug -PAPP_BASE_URL=https://your-domain.example
```

APK tạo tại:

```text
app\build\outputs\apk\debug\app-debug.apk
```
