# Smart TKB Android (WebView)

Project Android này là lớp vỏ WebView cho website Smart TKB. Backend FastAPI và PostgreSQL vẫn chạy trên server; APK không chứa dữ liệu thời khóa biểu.

## URL backend của APK hiện tại

APK 1.0.7 đang dùng trực tiếp URL cố định:

```text
https://teacher-timetable-three.vercel.app
```

URL này được khai báo trong `app/build.gradle.kts` và đóng vào `BuildConfig.APP_BASE_URL` khi build. APK hiện không dùng Google Apps Script, Firebase Hosting, `APK_CONFIG_URL` hoặc cơ chế URL động.

Build debug:

```powershell
.\gradlew.bat assembleDebug
```

APK tạo tại:

```text
app\build\outputs\apk\debug\app-debug.apk
```
