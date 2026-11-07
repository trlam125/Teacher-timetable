# Kế hoạch chỉnh sửa dữ liệu sau khi đã phân công và xếp lịch

Trạng thái: **Đã triển khai luồng xem trước/áp dụng, bản dự phòng và hoàn tác gần nhất.**

Mã thực hiện tại `app/services/change_impact/`, API `app/routers/project_changes.py` và giao diện `app/static/workspace/change-impact.js`. Bản xem trước hết hạn sau 15 phút. Bản dự phòng giữ đến khi xóa vĩnh viễn project; không có tác vụ tự xóa theo thời gian. Phần dưới giữ lại đặc tả và tiêu chí để đối chiếu khi bảo trì.

## 1. Mục tiêu

Cho phép quản trị viên quay lại sửa giáo viên, môn, lớp, khối, chương trình học, phân công và ràng buộc sau khi đã có lịch. Trước khi lưu thay đổi có ảnh hưởng, người dùng được xem rõ dữ liệu sẽ thay đổi, chọn cách xử lý và xác nhận.

Kết quả mong muốn:

- Giữ tối đa phần lịch còn hợp lệ.
- Không yêu cầu gỡ toàn bộ lịch chỉ để sửa một phân công.
- Tiết còn cần dạy nhưng mất vị trí xếp xuất hiện trong Kho tiết chưa xếp.
- Phân biệt rõ tiết đưa về kho, tiết dư bị bỏ do giảm nhu cầu và tiết bị xóa cùng phân công.
- Không tự gỡ tiết ghim/cố định hoặc tự chọn giáo viên thay thế.
- Có bản dự phòng để phục hồi dữ liệu trước một lần thay đổi quan trọng.
- Mỗi lần xác nhận áp dụng thành công toàn bộ hoặc giữ nguyên dữ liệu cũ khi thất bại.

## 2. Hiện trạng đã kiểm tra trong mã nguồn

Ứng dụng hiện không có một khóa chung duy nhất ngăn tất cả chỉnh sửa sau xếp lịch. Các giới hạn nằm ở từng nghiệp vụ:

| Vị trí | Hành vi hiện tại | Hướng xử lý |
|---|---|---|
| `app/routers/entities/assignment_updates.py` | Chặn đổi giáo viên nếu phân công đã có tiết xếp hoặc tiết cố định; chặn một số trường hợp giảm số tiết thấp hơn số đã xếp | Thay bằng phân tích ảnh hưởng và xác nhận, vẫn bảo vệ tiết cố định |
| `app/services/entities/updates/teacher.py` | Chặn bỏ môn giáo viên đang có phân công | Yêu cầu chuyển hoặc xóa các phân công liên quan có xác nhận |
| `app/services/entities/updates/school_class.py` | Có đồng bộ khi đổi khối; chặn xung đột với khóa lịch của khối mới | Mở rộng để xem trước và gỡ đúng các block bị ảnh hưởng |
| `app/services/entities/curriculum/sync.py` | Đồng bộ số tiết/chế độ theo chương trình khối, có các điều kiện từ chối | Dùng chung cơ chế xem trước cho thay đổi nhiều lớp |
| `app/routers/constraints.py` | Đã có xác nhận gỡ tiết khi sửa tiết tránh/khóa khối và bảo vệ tiết cố định | Tái sử dụng quy tắc nghiệp vụ, thống nhất giao diện xác nhận |
| `app/services/entities/deletion.py` | Đã có xác nhận gỡ đúng danh sách tiết, xác nhận xóa phân công liên quan | Mở rộng thông tin ảnh hưởng, tránh tạo luồng xác nhận riêng trùng chức năng |
| `app/services/edit_conflicts.py` | Có token chống ghi đè dữ liệu đã được người khác sửa | Giữ cơ chế này và kiểm tra thêm các dữ liệu phụ thuộc |
| `app/static/app-entities.js` | Có hộp thoại sửa, xác nhận gỡ tiết và đồng bộ lại dữ liệu | Thêm bước xem trước chi tiết; bổ sung chọn giáo viên khi sửa phân công |

Trước khi viết mã, rà soát lại các điểm này vì mã nguồn có thể đã thay đổi so với thời điểm lập kế hoạch.

## 3. Phạm vi và nguyên tắc

### 3.1. Những thao tác được hỗ trợ

- Sửa tên và thông tin hiển thị.
- Đổi giáo viên cho phân công đã có lịch.
- Tăng/giảm số tiết, đổi chế độ tiết đơn/đôi theo quy tắc của ứng dụng.
- Sửa tiết tránh của giáo viên/lớp và khóa lịch khối.
- Sửa chương trình khối hoặc chuyển lớp sang khối khác.
- Bỏ môn dạy của giáo viên, xóa lớp/môn/giáo viên có dữ liệu phụ thuộc, sau khi chọn cách xử lý.

### 3.2. Những việc không tự động thực hiện

- Không tự chạy lại toàn bộ bộ xếp sau mỗi lần lưu.
- Không tự đổi giáo viên ở các phân công khác để tạo chỗ trống.
- Không tự gỡ ghim/cố định, kể cả khi người dùng đã bấm mở chế độ chỉnh sửa.
- Không cho lưu dữ liệu sai tham chiếu, trùng phân công lớp–môn hoặc lịch đang xếp vi phạm ràng buộc cứng.
- Không bắt buộc tìm được lịch đầy đủ mới cho lưu: lịch có thể còn tiết trong kho. Tuy nhiên vẫn phải thỏa các kiểm tra cấu trúc và sức chứa bắt buộc.
- Chưa đưa thay đổi số ngày/buổi/tiết của toàn project vào đợt đầu. Loại thay đổi này tác động đến cách đánh số ô lịch và cần kế hoạch chuyển đổi riêng.

### 3.3. Ý nghĩa của “Mở khóa chỉnh sửa”

Đây là trạng thái giao diện giúp người dùng chủ động bật sửa dữ liệu có ảnh hưởng. Nó không thay thế phân quyền, kiểm tra hợp lệ hoặc xác nhận từng lần lưu.

Đề xuất nút **“Chỉnh sửa sau xếp lịch”** trên workspace. Khi bật, hiển thị thông báo ngắn: “Thay đổi có thể ảnh hưởng đến phân công và lịch. Bạn sẽ được xem trước khi áp dụng.”

- Sửa tên đơn thuần vẫn sử dụng luồng lưu thông thường.
- Thay đổi có ảnh hưởng phải qua bước xem trước.
- Tắt chế độ không hoàn tác những thay đổi đã lưu.
- Không cần khóa độc quyền project trong suốt thời gian người dùng mở chế độ này.

## 4. Quy tắc xử lý từng thay đổi

| Thay đổi | Phân công | Tiết đang xếp | Tiết ghim/cố định |
|---|---|---|---|
| Đổi tên lớp/môn/giáo viên | Giữ ID và liên kết | Giữ nguyên vị trí | Giữ nguyên |
| Đổi giáo viên | Đổi giáo viên đúng phân công được chọn; kiểm tra giáo viên mới có dạy môn đó | Giữ vị trí hợp lệ; đề xuất đưa block xung đột về kho | Giữ nếu vẫn hợp lệ; nếu xung đột thì chặn và yêu cầu xử lý riêng |
| Tăng số tiết | Cập nhật nhu cầu theo chương trình khối nếu có | Giữ lịch hiện tại; phần tăng nằm trong kho | Giữ nguyên |
| Giảm số tiết | Giảm nhu cầu, đồng bộ đúng nguồn chương trình | Nếu có tiết dư, người dùng chọn block bỏ; có thể đề xuất sẵn nhưng phải hiển thị | Không được tự bỏ; chặn nếu tổng tiết phải giữ vượt nhu cầu mới |
| Đổi chế độ tiết đơn/đôi | Cập nhật chế độ hợp lệ với số tiết và độ dài buổi | Giữ block hợp lệ; các block phải tổ chức lại được đưa về kho sau xác nhận | Chặn nếu cần phá cấu trúc block có tiết cố định |
| Thêm tiết tránh/khóa khối | Giữ phân công | Chỉ đưa các block xung đột về kho | Chặn xung đột; chỉ rõ tiết cần bỏ cố định trước |
| Bớt tiết tránh/khóa khối | Giữ phân công | Giữ lịch; chỉ mở thêm vị trí có thể xếp | Giữ nguyên |
| Đổi chương trình khối | Đồng bộ phân công của các lớp thuộc phạm vi thay đổi | Giữ tiết hợp lệ; phân biệt phần dư bị bỏ và phần còn thiếu cần xếp | Kiểm tra toàn bộ trước khi cho xác nhận |
| Đổi khối của lớp | Đối chiếu chương trình khối mới, nêu phân công dư/thiếu | Kiểm tra số tiết, chế độ và khóa khối mới | Không tự chuyển hoặc gỡ tiết cố định |
| Bỏ môn dạy của giáo viên | Phải chọn giáo viên thay thế hoặc xác nhận xóa phân công liên quan | Xử lý theo từng phân công được chuyển/xóa | Không tự gỡ |
| Xóa lớp/môn/giáo viên | Xem trước toàn bộ dữ liệu phụ thuộc; chọn chuyển hoặc xóa rõ ràng | Tiết của phân công bị xóa cũng bị xóa, không trở thành nhu cầu trong kho | Yêu cầu xử lý cố định trước khi thực hiện xóa dây chuyền |

Các điểm phải thống nhất:

1. **Kho tiết chưa xếp được tính từ nhu cầu phân công trừ số tiết đã xếp.** Không thêm một bảng kho riêng nếu không có yêu cầu lưu từng tiết độc lập.
2. Giảm 5 xuống 3 tiết khi đã xếp đủ 5 nghĩa là bỏ 2 tiết dư, không đưa 2 tiết ấy vào kho.
3. Giữ nhu cầu 5 nhưng gỡ 2 tiết xung đột nghĩa là còn 3 tiết trên lịch và 2 tiết trong kho.
4. Block tiết đôi là một đơn vị nguyên vẹn: khi một tiết trong block phải gỡ, xử lý cả block theo quy tắc hiện có, không để lại nửa block.
5. “Tiết được bảo vệ” phải xét cả `Lesson.locked` và phạm vi bao phủ của `FixedLesson`, không chỉ một cờ.
6. Nếu số tiết được điều khiển bởi chương trình khối, không cho sửa riêng một phân công thành cấu hình trái chương trình. Giao diện phải dẫn người dùng sửa chương trình và hiển thị phạm vi các lớp bị ảnh hưởng.

## 5. Luồng giao diện đề xuất

1. Quản trị viên bật **Chỉnh sửa sau xếp lịch** và mở mục cần sửa.
2. Nhập thông tin mới; dữ liệu nhập chỉ nằm trong form, chưa thay đổi lịch đã lưu.
3. Bấm **Xem ảnh hưởng**. Với thay đổi có ảnh hưởng, bước này thay cho lưu trực tiếp.
4. Hiện hộp thoại gồm:
   - Nội dung cũ → mới.
   - Số phân công cập nhật, chuyển giáo viên, xóa và còn thiếu.
   - Số tiết giữ nguyên, đưa về kho, bỏ do giảm nhu cầu và xóa cùng phân công.
   - Số block tương ứng, tránh hiểu nhầm một block đôi là một tiết.
   - Danh sách lớp, môn, giáo viên, thứ/buổi/tiết và lý do ảnh hưởng.
   - Các tiết cố định đang chặn thao tác và cách xử lý.
5. Nếu cần lựa chọn, cho chọn block bỏ hoặc giáo viên thay thế, rồi tính lại ảnh hưởng.
6. Nút **Áp dụng thay đổi** chỉ khả dụng khi không còn điều kiện chặn.
7. Áp dụng thành công: cập nhật bảng dữ liệu, phân công, lịch, kho, bộ lọc và thông báo. Giữ bộ lọc hiện tại nếu đối tượng vẫn tồn tại.
8. Hiện kết quả ngắn, ví dụ: “Đã đổi giáo viên. Giữ 3 tiết, đưa 1 tiết về kho.” Kèm **Xem lịch**, **Xem kho**, **Xem bản dự phòng** khi phù hợp.
9. Hủy ở bất kỳ bước nào trước áp dụng phải giữ nguyên dữ liệu đã lưu; giữ nội dung nhập để người dùng tiếp tục sửa nếu đóng phần xem trước.

Ví dụ xem trước:

> Đổi giáo viên Toán lớp 6A: cô Lan → cô Hoa.
>
> Cập nhật 1 phân công. Giữ 3 tiết. Đưa 1 tiết về kho vì cô Hoa đã có lịch vào thứ Ba, tiết 2. Không ảnh hưởng tiết cố định.
>
> [Quay lại chỉnh sửa] [Áp dụng thay đổi]

Nếu một block đôi xung đột, thông báo phải ghi “Đưa 2 tiết thuộc 1 block đôi về kho”, không ghi chỉ một tiết.

## 6. Thiết kế xử lý phía máy chủ

### 6.1. Dịch vụ phân tích ảnh hưởng dùng chung

Đề xuất thêm `app/services/change_impact/` gồm các phần: chuẩn hóa yêu cầu, dựng trạng thái dự kiến, đánh giá quy tắc, tạo kế hoạch áp dụng và tạo thông tin hiển thị.

Đầu vào: project, người thao tác, loại thay đổi, đối tượng, dữ liệu mới và các lựa chọn xử lý.

Đầu ra tối thiểu:

- `can_apply`: có được áp dụng không.
- `changes`: khác biệt giữa dữ liệu cũ và mới.
- `assignments`: ID và hành động dự kiến với từng phân công.
- `lesson_actions`: ID tiết/block, vị trí hiện tại, hành động và lý do.
- `blockers`: lỗi phải giải quyết trước, bao gồm xung đột cố định.
- `warnings`: thông tin có thể tiếp tục sau khi xác nhận, chẳng hạn chưa đủ giáo viên cho chương trình mới.
- `totals`: tổng số phân công, tiết, block theo từng hành động.
- `impact_token`: dấu xác nhận gắn với đúng trạng thái và lựa chọn đã xem.

Phần xem trước phải đọc và mô phỏng dữ liệu, không commit hoặc phát thông báo lịch. Nên dùng một cấu trúc trạng thái dự kiến độc lập với các ORM object đang được quản lý, tránh việc query làm tự flush những thay đổi thử.

Tái sử dụng bộ kiểm tra hiện có về trùng giáo viên/lớp, tiết tránh, khóa khối, biên buổi, sức chứa và block. Không viết một bộ quy tắc khác chỉ dành cho màn xem trước.

### 6.2. Hai bước API

Đường dẫn đề xuất, có thể điều chỉnh theo quy ước router khi triển khai:

- `POST /api/projects/{pid}/changes/preview`: trả kế hoạch, điều kiện chặn và token.
- `POST /api/projects/{pid}/changes/apply`: nhận lại yêu cầu, lựa chọn và token; kiểm tra rồi mới ghi.

Các API sửa hiện tại vẫn phải giữ phân quyền và bảo vệ dữ liệu. Chuyển dần phần nghiệp vụ sang dịch vụ dùng chung, tránh để API cũ trở thành đường bỏ qua xác nhận. Giữ tương thích với luồng sửa không ảnh hưởng lịch.

### 6.3. Chống thay đổi đồng thời

- Token gắn với người dùng, project, yêu cầu chuẩn hóa, lựa chọn và dấu vân tay của toàn bộ dữ liệu phụ thuộc.
- Phải xét cả phân công khác của giáo viên mới, tiết tránh, chương trình khối, block và tiết cố định; chỉ kiểm tra token của đối tượng đang sửa là chưa đủ.
- Có thể dùng token ký bằng khóa máy chủ và thời hạn ngắn; khi triển khai phải xác định thời hạn cụ thể và không ghi dữ liệu nhạy cảm không cần thiết vào token.
- Lúc áp dụng, lấy khóa ghi project bằng cơ chế `get_project_for_update`, đọc lại dữ liệu và tính lại kế hoạch.
- Nếu dữ liệu hoặc kế hoạch khác bản đã xem, trả trạng thái yêu cầu xem lại; không dùng xác nhận cũ để áp dụng một danh sách ảnh hưởng mới.
- Không giữ transaction hoặc khóa DB trong thời gian người dùng đang đọc hộp thoại.
- Ngăn bấm hai lần. Yêu cầu áp dụng lặp lại cùng một mã thao tác phải trả lại kết quả đã thực hiện, không tạo thêm bản dự phòng hoặc áp dụng lần nữa.

### 6.4. Giao dịch áp dụng

Trong cùng một transaction:

1. Kiểm tra quyền, project còn hoạt động, phiên bản và token xác nhận.
2. Tính lại ảnh hưởng dưới khóa ghi.
3. Lưu bản dự phòng nếu thay đổi có ảnh hưởng đến phân công/lịch.
4. Cập nhật dữ liệu, đồng bộ phân công và xử lý các block đã được xác nhận.
5. Chạy kiểm tra toàn vẹn với trạng thái lịch mới, cho phép thiếu tiết nhưng không cho lịch đã xếp vi phạm quy tắc cứng.
6. Lưu nhật ký thay đổi và kết quả thao tác.
7. Commit một lần. Chỉ phát cập nhật cho các máy khác sau commit.

Nếu bất kỳ bước nào lỗi, rollback cả dữ liệu, bản dự phòng vừa tạo và nhật ký chưa hoàn tất. Hộp thoại báo lỗi cụ thể và giữ nội dung đang nhập.

## 7. Bản dự phòng và phục hồi

Thùng rác của project và bản dự phòng trước chỉnh sửa là hai nhu cầu khác nhau. Thùng rác khôi phục project bị xóa; bản dự phòng phục hồi một trạng thái dữ liệu trước đó.

Đề xuất thêm lưu trữ snapshot theo project, có phiên bản định dạng, người tạo, thời gian, lý do, mã thao tác và dấu phiên bản trước/sau thay đổi.

Snapshot lưu cấu hình project và dữ liệu nghiệp vụ liên quan: tổ, môn, giáo viên, môn giáo viên dạy, khối, chương trình, lớp, phân công, tiết xếp, tiết cố định và nguyện vọng cần bảo toàn. Không sao chép hay phục hồi tài khoản toàn hệ thống, mật khẩu hoặc quyền trường.

- Tạo tự động trước khi áp dụng thay đổi có ảnh hưởng; đổi tên đơn thuần có thể chỉ ghi nhật ký.
- Không dùng nguyên API nhân bản project làm cơ chế hoàn tác: luồng clone hiện có không giữ nguyên toàn bộ dữ liệu như nguyện vọng, ID và liên kết chia sẻ.
- Đợt đầu chỉ cho **Hoàn tác lần thay đổi gần nhất** khi project chưa có thay đổi nghiệp vụ mới sau đó.
- Nếu đã có thay đổi mới, không phục hồi đè âm thầm. Hiển thị lý do chặn; phục hồi lịch sử tùy ý cần một luồng riêng có xem trước.
- Phục hồi phải nguyên tử, xử lý đúng thứ tự khóa ngoại, giữ định danh project và liên kết chia sẻ hiện tại, rồi kiểm tra toàn vẹn.
- Không khôi phục snapshot bằng cách phát lại thông báo cũ. Ghi một sự kiện mới rằng project đã được phục hồi.
- Chốt chính sách giữ/xóa bản dự phòng và hiển thị rõ cho người dùng; không tự đặt thời hạn xóa âm thầm.
- Khi xóa vĩnh viễn project, dọn cả snapshot và nhật ký liên quan theo chính sách đã chọn.

## 8. Các phần mã nguồn dự kiến tác động

| Nhóm | Tệp/thư mục | Công việc |
|---|---|---|
| Giao diện sửa | `app/static/app-entities.js`, `app/templates/workspace/` | Bật chế độ sửa, chọn giáo viên mới, xem trước, chọn cách xử lý, kết quả |
| API sửa | `app/routers/entities/assignment_updates.py`, `entity_updates.py` | Thay các điều kiện chặn phù hợp bằng kế hoạch có xác nhận |
| Giáo viên/lớp/khối | `app/services/entities/updates/` | Tách logic kiểm tra và áp dụng, hỗ trợ lựa chọn chuyển/xóa |
| Chương trình khối | `app/services/entities/curriculum/` | Tính ảnh hưởng nhiều lớp và đồng bộ nguyên tử |
| Ràng buộc | `app/routers/constraints.py` | Tích hợp xem trước thống nhất, giữ quy tắc bảo vệ cố định |
| Xóa dữ liệu | `app/services/entities/deletion.py`, router xóa | Hợp nhất xác nhận và chi tiết phụ thuộc |
| Chống xung đột | `app/services/edit_conflicts.py`, `app/services/projects.py` | Kiểm tra đầy đủ phụ thuộc và khóa ghi khi áp dụng |
| Block và toàn vẹn | `app/services/schedule_operations/` | Tái sử dụng kiểm tra block, khả thi và toàn vẹn |
| Thông báo | `app/services/schedule_live.py`, `schedule_notifications.py` | Chỉ công bố sau commit, thể hiện đúng thay đổi giáo viên và dữ liệu ngoài vị trí tiết |
| Snapshot/nhật ký | `app/models.py`, migration bootstrap và dịch vụ mới | Lưu, xem, phục hồi, dọn khi xóa project |

Kho tiết luôn hiển thị như hiện tại. Sau cập nhật, tính lại kho từ dữ liệu phân công/lịch mới, không lưu một số đếm độc lập dễ bị lệch.

## 9. Thứ tự triển khai

### Giai đoạn 1 — Rà soát và chốt quy tắc

- Lập danh sách thao tác hiện bị chặn và phân biệt nguyên nhân: bảo vệ dữ liệu, sai cấu trúc, lệch chương trình hay giới hạn giao diện.
- Chốt bảng hành vi ở mục 4; không thay mọi lỗi 409 bằng nút “Vẫn tiếp tục”.
- Chốt quy tắc bảo vệ cố định và đơn vị block.
- Chốt dữ liệu snapshot, điều kiện hoàn tác và chính sách lưu giữ.

Đầu ra: danh sách thao tác được mở và điều kiện vẫn phải chặn.

### Giai đoạn 2 — Nền tảng xem trước và bản dự phòng

- Dịch vụ phân tích ảnh hưởng, cấu trúc phản hồi và token xác nhận.
- API xem trước/áp dụng, khóa ghi, chống thao tác lặp.
- Snapshot, nhật ký và hoàn tác lần gần nhất.
- Hộp thoại ảnh hưởng dùng chung.

Đầu ra: một luồng thử hoàn chỉnh, chứng minh xem trước không ghi dữ liệu và áp dụng có thể phục hồi.

### Giai đoạn 3 — Sửa phân công đã có lịch

- Đổi giáo viên: giữ tiết hợp lệ, gỡ block xung đột sau xác nhận.
- Tăng/giảm số tiết với lựa chọn block dư.
- Đổi chế độ tiết đơn/đôi, bảo vệ cố định.
- Dẫn người dùng sang chương trình khối nếu đó là nguồn cấu hình bắt buộc.

Đây là giai đoạn nên hoàn thiện đầu tiên để giải quyết nhu cầu sửa thường gặp nhất.

### Giai đoạn 4 — Sửa dữ liệu ảnh hưởng nhiều phân công

- Thống nhất xem trước cho tiết tránh/khóa khối.
- Sửa chương trình khối và đổi khối của lớp.
- Bỏ môn dạy, chuyển phân công và xóa dữ liệu có phụ thuộc.
- Gộp ảnh hưởng trùng lặp, không đếm một tiết nhiều lần khi có nhiều nguyên nhân.

### Giai đoạn 5 — Hoàn thiện vận hành

- Cập nhật lịch, kho, danh sách và các máy đang mở cùng project sau commit.
- Bổ sung nhật ký dễ đọc và hướng dẫn thao tác.
- Kiểm tra trên bản sao dữ liệu đủ lớn, sau đó mới bật cho project vận hành.

## 10. Kế hoạch kiểm chứng khi triển khai

Việc kiểm chứng dưới đây thực hiện khi bắt đầu làm chức năng. **Không thêm lại bước chạy test tự động trong GitHub Actions**; giữ lựa chọn hiện tại của chủ dự án. Những kiểm tra tự động cần thiết có thể chạy thủ công ở máy phát triển.

Các tình huống bắt buộc:

1. Đổi tên giữ nguyên toàn bộ ID, phân công, vị trí và cố định.
2. Đổi sang giáo viên rảnh hoàn toàn: giữ toàn bộ lịch.
3. Giáo viên mới trùng một tiết: chỉ gỡ đúng block liên quan sau xác nhận.
4. Xung đột với cố định hoặc `Lesson.locked`: chặn, chỉ rõ tiết và không thay dữ liệu.
5. Giảm nhu cầu khi có tiết dư: bỏ đúng block được chọn, không tạo nhu cầu giả trong kho.
6. Tăng nhu cầu: giữ lịch, tăng đúng phần thiếu trong kho.
7. Chuyển chế độ tiết đơn/đôi: không mất nửa block hoặc vượt biên buổi.
8. Đổi chương trình khối: tính đúng ảnh hưởng nhiều lớp, không cập nhật một phần khi có lỗi.
9. Chuyển khối, bỏ môn dạy, xóa dữ liệu phụ thuộc: không để tham chiếu mồ côi.
10. Hủy xem trước: DB, kho, thông báo và bản dự phòng không thay đổi.
11. Hai người cùng sửa: bản xem trước cũ bị yêu cầu tính lại, kể cả khi thay đổi nằm ở giáo viên mới hoặc ràng buộc liên quan.
12. Bấm áp dụng hai lần, tải lại hoặc mất mạng sau commit: không áp dụng lặp; tải lại phải xác định được kết quả cuối cùng.
13. Lỗi giữa lúc áp dụng: rollback toàn bộ, không phát thông báo giả.
14. Hoàn tác ngay sau thay đổi: khôi phục đúng cấu hình, phân công, lịch, block và nguyện vọng đã lưu.
15. Hoàn tác sau một thay đổi mới khác: không ghi đè dữ liệu mới.
16. Giáo viên, admin trường khác và người không có quyền: không xem/áp dụng/phục hồi thay đổi.
17. Project trong Thùng rác: không cho chỉnh sửa hoặc phục hồi snapshot trực tiếp khi chưa khôi phục project.
18. Lịch chia sẻ và cổng giáo viên: phản ánh đúng dữ liệu đã commit, không thấy trạng thái xem trước.

## 11. Tiêu chí hoàn thành

- Quản trị viên sửa được phân công đã có lịch mà không cần dọn toàn bộ lịch trước.
- Mọi thay đổi có ảnh hưởng đều có danh sách trước/sau và xác nhận đúng phiên bản.
- Giữ phần lịch hợp lệ, xử lý block nguyên vẹn và bảo vệ cố định.
- Phân công, chương trình khối, lịch và số tiết trong kho luôn thống nhất.
- Có bản dự phòng và hoàn tác gần nhất với điều kiện rõ ràng.
- Không ghi dở dang, không ghi đè thay đổi đồng thời, không áp dụng lặp.
- Không thay đổi quyền truy cập hiện có và không chạy test trong GitHub Actions.

## 12. Điểm cần chốt khi bắt đầu thực hiện

- Khi giảm tiết, giao diện đề xuất block bỏ theo tiêu chí nào; người dùng luôn được xem và thay lựa chọn.
- Chính sách giữ bản dự phòng: theo số bản, thời gian hay dọn thủ công.
- Có cần phục hồi nhiều mốc lịch sử ngay đợt đầu hay chỉ hoàn tác lần gần nhất như đề xuất.
- Ưu tiên triển khai đổi giáo viên và sửa số tiết trước, sau đó mới mở các thay đổi ảnh hưởng cả khối.

Lựa chọn đã áp dụng: đề xuất bỏ các block không cố định ở cuối lịch khi giảm tiết, cho người dùng đổi lựa chọn trước khi xác nhận; giữ bản dự phòng đến khi xóa project; chỉ hoàn tác thay đổi gần nhất nếu dữ liệu chưa thay đổi tiếp. Thay đổi kích thước tuần học và phục hồi tùy ý nhiều mốc lịch sử vẫn nằm ngoài phạm vi.
