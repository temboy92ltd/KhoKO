# Kho Khải Oanh

Website Python Flask quản lý xuất nhập phụ kiện cửa hàng xe máy. Giao diện tiếng Việt, sử dụng được trên máy tính và điện thoại.

## Chức năng

- Đăng nhập, đăng xuất, đổi mật khẩu. Mật khẩu được băm, không lưu dạng văn bản.
- Admin tạo tài khoản Admin/Nhân viên và xóa quyền truy cập của tài khoản khác; không được xóa chính mình. Lịch sử của tài khoản bị xóa vẫn được giữ, phiên đăng nhập cũ bị chặn ở yêu cầu tiếp theo. Tên đăng nhập đã dùng không tái sử dụng.
- Nhập phụ kiện: tên, màu sắc, dòng xe, số lượng, ghi chú tùy chọn. Cùng tên + màu + dòng xe thì cộng tồn; khác một thông tin thì tạo phân loại riêng. Khi nhập lại, chọn phụ kiện đã có để tránh khác cách viết.
- Xuất phụ kiện: tìm tên/màu/dòng xe, xem tồn, chọn số lượng. Chặn số lượng không hợp lệ hoặc vượt tồn. Cập nhật tồn và lịch sử trong cùng giao dịch database.
- Chống ghi phiếu lặp khi gửi lại cùng biểu mẫu. Với phiếu mới, hệ thống coi là một giao dịch mới.
- Admin xem lịch sử theo ngày/tháng/quý, lọc nhập/xuất, tải CSV mở bằng Excel; thời gian theo Việt Nam.
- Biểu đồ thanh tồn hiện tại gộp theo tên phụ kiện; danh sách chi tiết và cảnh báo theo tên + màu + dòng xe. Biểu đồ không phải tồn cuối kỳ lịch sử.
- Mức tồn tối thiểu mặc định 5, admin thay đổi ngay trên bảng tồn kho. Tồn ≤ mức này sẽ được cảnh báo.
- Phân trang bảng tồn, tìm phụ kiện xuất và lịch sử báo cáo.

## 1. Chạy trên Windows (PowerShell)

Cài Python 3.12. Giải nén, mở PowerShell ở thư mục chứa `app.py`.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

$env:SECRET_KEY = (.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))")
$env:ADMIN_USERNAME = "admin"
$env:ADMIN_PASSWORD = Read-Host "Nhap mat khau admin (10-128 ky tu)" -MaskInput

.\.venv\Scripts\python.exe -m flask --app app init-db
.\.venv\Scripts\python.exe app.py
```

`-MaskInput` cần PowerShell 7. Nếu dùng Windows PowerShell 5, thay dòng nhập mật khẩu bằng:

```powershell
$securePassword = Read-Host "Nhap mat khau admin (10-128 ky tu)" -AsSecureString
$env:ADMIN_PASSWORD = [System.Net.NetworkCredential]::new("", $securePassword).Password
Remove-Variable securePassword
```

Mở http://127.0.0.1:5000. Đăng nhập bằng `admin` và mật khẩu bạn vừa đặt. Không có mật khẩu mặc định.

Lần sau mở PowerShell, chạy lại dòng đặt SECRET_KEY và lệnh `python app.py`. Database được giữ trong `instance/kho.db`; không cần tạo lại tài khoản. Muốn giữ phiên đăng nhập qua các lần chạy, đặt cùng một SECRET_KEY ở mỗi lần chạy. Sao lưu database khi đã dừng ứng dụng bằng cách copy `instance/kho.db`.

File `.env.example` chỉ là danh sách biến tham khảo: ứng dụng không tự đọc file `.env`.

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export ADMIN_USERNAME=admin
read -s -p 'Admin password: ' ADMIN_PASSWORD
export ADMIN_PASSWORD
python -m flask --app app init-db
python app.py
```

## 2. Đưa lên Render để hoạt động online

### Bước A — Đưa mã nguồn lên GitHub

Tạo repository riêng tư mới. Upload tất cả mã nguồn trong thư mục `kho-khai-oanh`, bảo đảm **app.py, requirements.txt và render.yaml ở gốc repository**.

Không upload `.venv`, database, `.env` hoặc mật khẩu thật. Cấu hình `.gitignore` đã kèm sẵn. Không bật dữ liệu minh họa trong môi trường thật; database mới bắt đầu trống.

### Bước B — Tạo PostgreSQL

Trên [Render](https://dashboard.render.com/), chọn **New → Postgres**. Đặt tên `kho-khai-oanh-db`, chọn vùng phù hợp (ví dụ Singapore nếu có).

Sau khi database hoạt động, sao chép **Internal Database URL**. Chọn database và web service cùng vùng. URL này là thông tin bí mật.

Dùng PostgreSQL khi chạy Render. SQLite trong filesystem tạm của Render có thể mất dữ liệu khi restart/deploy. PostgreSQL tách biệt giúp giữ tài khoản và tồn kho qua các lần triển khai lại.

**Lưu ý gói miễn phí:** theo tài liệu Render, Free Postgres hết hạn sau 30 ngày và không có backup. Free Web Service ngủ sau 15 phút không có truy cập. Cửa hàng sử dụng dài hạn nên chọn database trả phí hoặc PostgreSQL khác có backup. Kiểm tra gói và giá hiển thị tại thời điểm tạo.

### Bước C — Tạo Web Service

Chọn **New → Web Service**, kết nối repository GitHub.

| Thiết lập | Giá trị |
|---|---|
| Runtime | Python 3 |
| Region | Cùng vùng với PostgreSQL |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python -m flask --app app init-db && gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 app:app` |
| Health Check Path | `/health` |

Thêm Environment Variables:

| Biến | Giá trị |
|---|---|
| SECRET_KEY | Chuỗi bí mật ngẫu nhiên dài; có thể tạo bằng `python -c "import secrets; print(secrets.token_hex(32))"` |
| DATABASE_URL | Internal Database URL của PostgreSQL |
| ADMIN_USERNAME | `admin` hoặc tên hợp lệ bạn chọn |
| ADMIN_PASSWORD | Mật khẩu riêng, 10–128 ký tự |

Tên đăng nhập dùng a-z/0-9/dấu chấm/gạch ngang/gạch dưới, dài 3–50 ký tự. Giữ SECRET_KEY ổn định giữa các lần deploy. Render tự đặt biến `RENDER`; app dùng biến này để bật cookie HTTPS và yêu cầu cấu hình database.

Chọn **Create Web Service**. Lệnh Start tự tạo các bảng và tài khoản admin lần đầu. Nếu admin đã tồn tại, lệnh không đổi mật khẩu. Sau khi deploy thành công, mở URL `https://...onrender.com` Render cấp.

Bạn cũng có thể chọn **New → Blueprint**, dùng `render.yaml` đã kèm. Blueprint tạo Web Service gói Free, yêu cầu nhập `DATABASE_URL` và `ADMIN_PASSWORD`; cần tạo PostgreSQL trước như Bước B. SECRET_KEY được Render tạo ngẫu nhiên.

Mã nguồn được chuẩn bị cho Render; chưa được triển khai lên tài khoản Render của bạn.

## 3. Sử dụng

1. Đăng nhập Admin → Tài khoản → tạo tài khoản nhân viên.
2. Nhập kho → nhập tên, màu, dòng xe, số lượng → xác nhận.
3. Xuất kho → tìm phụ kiện → Chọn xuất kho → nhập số lượng → xác nhận.
4. Tồn kho → theo dõi hàng sắp hết; admin điều chỉnh mức tối thiểu.
5. Báo cáo → chọn ngày nằm trong kỳ mong muốn → chọn Theo ngày/tháng/quý → Xem báo cáo.
6. Tải CSV để mở trong Excel. Bộ lọc loại giao dịch áp dụng bảng và CSV; ô tổng nhập/xuất luôn thể hiện cả kỳ.

Ví dụ: chọn `15/08/2026` với kỳ Quý sẽ lấy toàn bộ Quý 3 (01/07–30/09). Không cần nhập ngày đầu quý.

## 4. Sao lưu và bảo trì

- Database PostgreSQL là nguồn dữ liệu chính. CSV báo cáo chỉ chứa lịch sử lọc, **không** thay thế backup đầy đủ.
- Thiết lập backup trong dịch vụ PostgreSQL. Nếu dùng công cụ `pg_dump`, dùng External Database URL theo hướng dẫn nhà cung cấp và giữ backup ở vị trí riêng.
- Thay đổi mật khẩu bootstrap `ADMIN_PASSWORD` sau lần đầu không đổi mật khẩu đã lưu. Đổi trên trang Đổi mật khẩu; khi quên, người vận hành có shell truy cập ứng dụng có thể chạy:

```bash
python -m flask --app app reset-password admin
```

Lệnh hỏi mật khẩu mới và xác nhận, không đưa mật khẩu vào tham số dòng lệnh. Render Free không có Shell, nên cần môi trường quản trị tin cậy kết nối database (hoặc nâng cấp dịch vụ để dùng Shell).

- Giữ một Gunicorn worker như cấu hình hiện tại. Giới hạn đăng nhập lưu trong bộ nhớ: 10 lần/phút/IP, đặt lại khi tiến trình restart. Khi mở rộng nhiều worker/instance, cần chuyển bộ lưu giới hạn sang Redis và rà soát proxy/IP trước khi scale.
- Các giao dịch kho đã xác nhận không có nút sửa/xóa nhằm bảo toàn lịch sử. Chưa có phiếu điều chỉnh, import Excel hay giá bán; đây là phiên bản quản lý số lượng theo yêu cầu.
- `init-db` chỉ tạo bảng mới, không thực hiện migration schema đã tồn tại. Khi bổ sung thay đổi bảng ở phiên bản sau, cần migration và backup trước.
- Tìm kiếm theo chữ có dấu/không dấu phụ thuộc cách ghi tên; bản này không tự chuẩn hóa thành tìm không dấu.

## 5. Kiểm thử

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Các kiểm thử gồm đăng nhập/phân quyền, cộng tồn theo biến thể, số lượng sai, xuất vượt tồn, phiếu lặp, hai yêu cầu xuất đồng thời, xóa tài khoản và thu hồi phiên, biên tháng/quý, CSV, CSRF, bảo vệ mật khẩu admin khi khởi động lại. Bộ test dùng SQLite tạm riêng biệt; không chạm dữ liệu thật. Chưa kiểm thử trên PostgreSQL Render thực tế.

Database của bản cài đặt mới bắt đầu trống; hãy nhập phụ kiện thực tế sau khi tạo admin.

## Tài liệu Render đã đối chiếu

- https://render.com/docs/deploy-flask
- https://render.com/docs/deploys
- https://render.com/docs/free
- https://render.com/docs/postgresql
- https://render.com/docs/blueprint-spec
