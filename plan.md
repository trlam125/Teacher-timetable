# PLAN.md

## Mục tiêu

Chuẩn hóa toàn bộ typography của project **Teacher Timetable / Smart TKB** sang một font duy nhất là **Be Vietnam Pro** để:

- Hiển thị tiếng Việt đều và rõ hơn.
- Tránh tình trạng chữ không đồng đều giữa tiêu đề, button, input, select và nội dung.
- Loại bỏ các font cũ đang dùng rải rác như:
  - `Sans Serif Collection`
  - `Plus Jakarta Sans`
  - `Cambria`
  - `Times New Roman`
  - `Aptos`
- Giữ giao diện nhất quán trên Windows, Android và các trình duyệt phổ biến.

## Font sử dụng

Font chính:

```css
font-family: "Be Vietnam Pro", sans-serif;
```

Các weight được phép dùng:

| Weight | Mục đích |
|---|---|
| 400 | Nội dung thông thường |
| 500 | Label, input, text cần nhấn nhẹ |
| 600 | Button, menu, navigation |
| 700 | Heading chính |

Không sử dụng weight ngoài `400`, `500`, `600`, `700` nếu không thực sự cần thiết.

## Giai đoạn 1 — Kiểm tra toàn bộ font hiện tại

Tìm toàn project các từ khóa:

```text
font-family
font-weight
Plus Jakarta Sans
Sans Serif Collection
Cambria
Times New Roman
Aptos
serif
```

Kiểm tra trong:

```text
static/
templates/
app/
android/
```

Đặc biệt rà soát:

```text
*.css
*.html
*.js
*.py
*.xml
```

Mục tiêu:

- Xác định tất cả font đang dùng.
- Không bỏ sót font inline trong HTML.
- Không bỏ sót style được sinh từ Python/JavaScript.
- Không thay đổi font icon nếu project đang dùng icon font riêng.

## Giai đoạn 2 — Thêm Be Vietnam Pro

Nếu dùng Google Fonts, thêm vào CSS chính:

```css
@import url("https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700&display=swap");
```

Hoặc thêm vào `<head>`:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link
    href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700&display=swap"
    rel="stylesheet"
>
```

Ưu tiên chỉ khai báo font ở một nơi dùng chung để tránh tải trùng.

## Giai đoạn 3 — Chuẩn hóa CSS global

Thiết lập font chung:

```css
html,
body {
    font-family: "Be Vietnam Pro", sans-serif;
}

body {
    font-weight: 400;
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
    text-rendering: optimizeLegibility;
}
```

Chuẩn hóa form control:

```css
button,
input,
textarea,
select {
    font-family: inherit;
}
```

Heading:

```css
h1,
h2 {
    font-weight: 700;
}

h3,
h4,
h5,
h6 {
    font-weight: 600;
}
```

Button:

```css
button,
.btn {
    font-weight: 600;
}
```

Label:

```css
label {
    font-weight: 500;
}
```

Navigation:

```css
nav,
.nav-item,
.sidebar-item {
    font-weight: 600;
}
```

## Giai đoạn 4 — Xóa font cũ

Thay toàn bộ các khai báo như:

```css
font-family: "Sans Serif Collection", sans-serif;
font-family: "Plus Jakarta Sans", sans-serif;
font-family: Cambria, serif;
font-family: "Times New Roman", serif;
font-family: Aptos, sans-serif;
```

thành:

```css
font-family: "Be Vietnam Pro", sans-serif;
```

Hoặc nếu element đã nằm trong phạm vi global:

```css
font-family: inherit;
```

Ưu tiên `inherit` để tránh lặp code.

## Giai đoạn 5 — Kiểm tra các component dễ bị lệch font

Rà soát kỹ:

- Button
- Input
- Select
- Textarea
- Modal
- Popup
- Toast
- Form đăng nhập
- Form đăng ký
- Form OTP
- Quên mật khẩu
- Sidebar
- Navbar
- Dashboard card
- Bảng thời khóa biểu
- Bảng danh sách giáo viên
- Project page
- Tooltip
- Dropdown
- Empty state
- Loading state

Đảm bảo không có component nào dùng font mặc định của browser.

## Giai đoạn 6 — Kiểm tra responsive

Test ít nhất các độ rộng:

```text
320px
375px
768px
1024px
1366px
1920px
```

Kiểm tra:

- Chữ có tràn button không.
- Text có bị xuống dòng bất thường không.
- Tiêu đề có quá cao không.
- Dấu tiếng Việt có bị cắt không.
- Input/select có cùng chiều cao không.
- Navbar/sidebar có bị lệch khi font thay đổi không.

## Giai đoạn 7 — Kiểm tra trình duyệt

Test tối thiểu:

```text
Chrome
Edge
Firefox
Android Chrome
```

Nếu có điều kiện:

```text
Safari / iOS
```

Kiểm tra các chuỗi tiếng Việt:

```text
Thời khóa biểu
Quản lý giáo viên
Đăng ký tài khoản
Xác nhận mã OTP
Quên mật khẩu
Cập nhật thông tin
Lịch giảng dạy
```

Mục tiêu là dấu tiếng Việt, độ cao chữ và khoảng cách phải đồng đều.

## Giai đoạn 8 — Kiểm tra font weight

Không dùng tùy tiện:

```css
font-weight: bold;
font-weight: bolder;
font-weight: 800;
font-weight: 900;
```

Chuẩn hóa về:

```text
400
500
600
700
```

Nếu style cũ có:

```css
font-weight: bold;
```

thì đổi thành:

```css
font-weight: 700;
```

nếu là heading, hoặc:

```css
font-weight: 600;
```

nếu là button/menu.

## Giai đoạn 9 — Dọn code thừa

Sau khi đổi font:

- Xóa import Google Font cũ.
- Xóa `@font-face` cũ nếu không còn dùng.
- Xóa biến CSS font cũ.
- Xóa comment font cũ.
- Không để nhiều khai báo `font-family` lặp lại không cần thiết.
- Không xóa icon font hoặc font dùng riêng cho biểu tượng nếu vẫn còn được sử dụng.

## Giai đoạn 10 — Kiểm tra build

Chạy kiểm tra project:

```bash
python -m compileall app
```

Nếu có frontend build riêng thì chạy build tương ứng.

Kiểm tra console trình duyệt:

```text
Không có lỗi tải font
Không có 404 font
Không có CSP error
Không có CSS parse error
```

## Giai đoạn 11 — Test chức năng sau khi đổi font

Test toàn bộ luồng chính:

```text
Đăng nhập
Đăng ký
OTP
Gửi lại OTP
Quên mật khẩu
Đổi email
Dashboard
Thời khóa biểu
Giáo viên
Project
Export
Popup
Responsive
```

Việc đổi font không được làm ảnh hưởng logic JavaScript hoặc layout chức năng.

## Tiêu chí hoàn thành

Project được coi là hoàn tất khi:

- [ ] Toàn bộ UI dùng `Be Vietnam Pro`.
- [ ] Không còn `Sans Serif Collection`.
- [ ] Không còn `Plus Jakarta Sans`.
- [ ] Không còn `Cambria`.
- [ ] Không còn `Times New Roman`.
- [ ] Không còn `Aptos`.
- [ ] Input/button/select/textarea dùng cùng font.
- [ ] Chỉ dùng weight `400`, `500`, `600`, `700`.
- [ ] Tiếng Việt hiển thị đồng đều.
- [ ] Không có lỗi font trong console.
- [ ] Không có layout bị vỡ sau khi đổi font.
- [ ] Desktop và mobile hiển thị thống nhất.

## Kết quả mong muốn

Typography cuối cùng:

```text
Font: Be Vietnam Pro

Body:       400
Label:      500
Input:      400
Menu:       600
Button:     600
H3-H6:      600
H1-H2:      700
```

Mục tiêu cuối là giao diện **gọn, hiện đại, dễ đọc, đồng đều và tối ưu cho tiếng Việt**.
