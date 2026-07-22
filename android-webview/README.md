# Smart TKB Android (WebView)

Project Android này là lớp vỏ riêng cho website Smart TKB. Backend FastAPI và PostgreSQL vẫn chạy trên máy chủ hiện tại; project không sao chép hay thay đổi mã nguồn web.

## Chạy với ngrok

Tại thư mục gốc `Teacher-timetable`, chạy:

```bat
run-ngrok.bat
```

APK hiện được cấu hình để mở trực tiếp URL:

```text
https://yahoo-speech-radiation.ngrok-free.dev
```

Nếu URL ngrok thay đổi, sửa hằng số `SERVER_URL` trong file:

```text
app/src/main/java/vn/smarttkb/app/MainActivity.java
```

Sau đó build lại APK. Ứng dụng không hiển thị màn hình nhập URL và không lưu URL động trên thiết bị.

Máy tính đang chạy FastAPI, PostgreSQL và ngrok phải luôn bật. Nếu một trong ba thành phần dừng, APK sẽ không kết nối được.

## Build APK debug

Yêu cầu JDK 17 trở lên và Android SDK 35. Project đã có Gradle Wrapper nên không cần cài Gradle riêng.

Từ thư mục `android-webview`, chạy Gradle:

```powershell
.\gradlew.bat assembleDebug
```

APK được tạo tại:

```text
app/build/outputs/apk/debug/app-debug.apk
```

APK debug dùng để cài thử trực tiếp. Khi phát hành chính thức cần tạo keystore và cấu hình bản release có chữ ký.

## Các chức năng lớp Android

- Mở trực tiếp URL ngrok được khai báo trong mã nguồn.
- Giữ cookie đăng nhập WebView.
- JavaScript và local storage cho giao diện hiện tại.
- Điều hướng Back bằng nút hệ thống Android.
- Kéo-thả bằng cảm ứng: giữ thẻ tiết học khoảng 0,3 giây, kéo tới ô đích rồi thả. Vuốt ngay không giữ vẫn cuộn trang bình thường.
- Thông báo khi mất mạng hoặc máy chủ ngừng hoạt động.
- Tải file xuất từ website vào thư mục Downloads, kèm cookie phiên đăng nhập.
- Chỉ cho phép kết nối HTTPS; không chấp nhận chứng chỉ lỗi hoặc HTTP thuần.
