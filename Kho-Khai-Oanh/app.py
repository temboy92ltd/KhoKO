import csv
import io
import os
import re
import secrets
from datetime import datetime, timedelta, date
from functools import wraps
from zoneinfo import ZoneInfo

import click
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for, Response
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import CheckConstraint, UniqueConstraint, func, or_, update, text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash

TZ = ZoneInfo('Asia/Ho_Chi_Minh')
db = SQLAlchemy()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=[], storage_uri='memory://')


def now_local():
    return datetime.now(TZ).replace(tzinfo=None)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False, unique=True)
    name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(10), nullable=False, default='staff')
    active = db.Column(db.Boolean, nullable=False, default=True)
    __table_args__ = (CheckConstraint("role in ('admin','staff')"),)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    color = db.Column(db.String(60), nullable=False)
    vehicle = db.Column(db.String(120), nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    minimum = db.Column(db.Integer, nullable=False, default=5)
    __table_args__ = (UniqueConstraint('name', 'color', 'vehicle'), CheckConstraint('stock >= 0'), CheckConstraint('minimum >= 0'))


class Movement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    kind = db.Column(db.String(3), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now_local, index=True)
    note = db.Column(db.String(250), nullable=False, default='')
    token = db.Column(db.String(64), unique=True, nullable=False)
    product = db.relationship(Product)
    user = db.relationship(User)
    __table_args__ = (CheckConstraint('quantity > 0'), CheckConstraint("kind in ('in','out')"),)


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not g.user:
            return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return wrapped


def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user.role != 'admin':
            abort(403)
        return fn(*args, **kwargs)
    return wrapped


def text_field(key, maxlen):
    value = ' '.join(request.form.get(key, '').split())
    if not value or len(value) > maxlen:
        raise ValueError('Vui lòng điền đầy đủ thông tin và không vượt quá độ dài cho phép.')
    return value


def integer(key, minimum=1):
    raw = request.form.get(key, '')
    if not re.fullmatch(r'\d{1,9}', raw):
        raise ValueError('Số lượng phải là số nguyên hợp lệ.')
    value = int(raw)
    if not minimum <= value <= 100000000:
        raise ValueError(f'Giá trị phải từ {minimum:,} đến 100.000.000.')
    return value


def search_products(q):
    query = Product.query
    # Escape LIKE wildcards so search input is treated as literal text.
    escaped = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    if q:
        query = query.filter(or_(*(col.ilike(f'%{escaped}%', escape='\\') for col in (Product.name, Product.color, Product.vehicle))))
    return query.order_by(Product.name, Product.color, Product.vehicle)


def period_bounds(args):
    mode = args.get('period', 'month')
    if mode not in ('day', 'month', 'quarter'):
        raise ValueError('Kỳ báo cáo không hợp lệ.')
    value = date.fromisoformat(args.get('date') or now_local().date().isoformat())
    if not 2000 <= value.year <= 2100:
        raise ValueError('Năm báo cáo phải từ 2000 đến 2100.')
    if mode == 'day':
        start = value
        end = start + timedelta(days=1)
        label = start.strftime('%d/%m/%Y')
    else:
        month = value.month if mode == 'month' else ((value.month - 1) // 3) * 3 + 1
        start = date(value.year, month, 1)
        nextmonth = month + (1 if mode == 'month' else 3)
        end = date(value.year + (nextmonth > 12), ((nextmonth - 1) % 12) + 1, 1)
        label = f'Tháng {month:02d}/{value.year}' if mode == 'month' else f'Quý {(month-1)//3+1}/{value.year}'
    return mode, value, datetime.combine(start, datetime.min.time()), datetime.combine(end, datetime.min.time()), label


def create_app(config=None):
    app = Flask(__name__)
    uri = os.getenv('DATABASE_URL', 'sqlite:///kho.db')
    if uri.startswith(('postgres://', 'postgresql://')):
        uri = re.sub(r'^postgres(?:ql)?://', 'postgresql+psycopg://', uri)
    if os.getenv('RENDER') and (not os.getenv('SECRET_KEY') or not uri.startswith('postgresql+psycopg://')):
        raise RuntimeError('Render cần SECRET_KEY và DATABASE_URL PostgreSQL để lưu dữ liệu bền vững.')
    app.config.update(SECRET_KEY=os.getenv('SECRET_KEY') or secrets.token_hex(32), SQLALCHEMY_DATABASE_URI=uri,
                      SQLALCHEMY_TRACK_MODIFICATIONS=False, SQLALCHEMY_ENGINE_OPTIONS={'pool_pre_ping': True}, SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=bool(os.getenv('RENDER')),
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=8), MAX_CONTENT_LENGTH=1024*1024)
    if config:
        app.config.update(config)
    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    @app.before_request
    def load_user():
        g.user = db.session.get(User, session.get('uid')) if session.get('uid') else None
        if g.user and not g.user.active:
            session.clear()
            g.user = None

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'; base-uri 'self'"
        if g.get('user') or request.endpoint == 'login':
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.context_processor
    def context():
        return dict(current_user=g.get('user'), today=now_local().date().isoformat())

    @app.template_filter('number')
    def number(value):
        return f'{value:,}'.replace(',', '.')

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.route('/login', methods=['GET', 'POST'])
    @limiter.limit('10 per minute', methods=['POST'])
    def login():
        if g.user:
            return redirect(url_for('dashboard'))
        if request.method == 'POST':
            user = User.query.filter_by(username=request.form.get('username','').strip().lower(), active=True).first()
            if user and check_password_hash(user.password_hash, request.form.get('password','')):
                session.clear()
                session['uid'] = user.id
                session.permanent = True
                return redirect(url_for('dashboard'))
            flash('Tên đăng nhập hoặc mật khẩu không đúng.', 'error')
        return render_template('login.html')

    @app.post('/logout')
    @login_required
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.get('/')
    @login_required
    def dashboard():
        q = request.args.get('q','').strip()[:120]
        page = request.args.get('page', 1, type=int)
        products = search_products(q).paginate(page=page, per_page=20, error_out=False)
        stats = dict(total=db.session.query(func.coalesce(func.sum(Product.stock), 0)).scalar(),
                     variants=Product.query.count(), low=Product.query.filter(Product.stock <= Product.minimum).count())
        todaystart = datetime.combine(now_local().date(), datetime.min.time())
        totals = dict(db.session.query(Movement.kind, func.sum(Movement.quantity)).filter(Movement.created_at >= todaystart).group_by(Movement.kind).all())
        recent = Movement.query.order_by(Movement.created_at.desc(), Movement.id.desc()).limit(8).all() if g.user.role == 'admin' else []
        return render_template('dashboard.html', products=products, stats=stats, totals=totals, q=q, recent=recent)

    @app.route('/stock-in', methods=['GET', 'POST'])
    @login_required
    def stock_in():
        if request.method == 'POST':
            try:
                name, color, vehicle = text_field('name',120), text_field('color',60), text_field('vehicle',120)
                qty = integer('quantity')
                token = request.form.get('token','')
                if len(token) != 64:
                    raise ValueError('Phiếu không hợp lệ. Vui lòng tải lại trang.')
                if Movement.query.filter_by(token=token).first():
                    flash('Phiếu này đã được ghi nhận.', 'info')
                    return redirect(url_for('stock_in'))
                product = Product.query.filter_by(name=name, color=color, vehicle=vehicle).first()
                if not product:
                    product = Product(name=name, color=color, vehicle=vehicle, stock=0)
                    db.session.add(product)
                    db.session.flush()
                result = db.session.execute(update(Product).where(Product.id == product.id, Product.stock <= 100000000-qty).values(stock=Product.stock+qty))
                if result.rowcount != 1:
                    raise ValueError('Tồn kho vượt giới hạn cho phép.')
                db.session.add(Movement(product_id=product.id, user_id=g.user.id, kind='in', quantity=qty, token=token, note=request.form.get('note','').strip()[:250]))
                db.session.commit()
                flash(f'Đã nhập {qty} phụ kiện: {name}.', 'success')
                return redirect(url_for('stock_in'))
            except ValueError as e:
                db.session.rollback()
                flash(str(e), 'error')
            except IntegrityError:
                db.session.rollback()
                flash('Phiếu đã được xử lý hoặc phụ kiện vừa được tạo bởi người khác. Kiểm tra tồn kho trước khi nhập lại.', 'info')
        products = Product.query.order_by(Product.name).all()
        return render_template('stock_in.html', products=products, token=secrets.token_hex(32))

    @app.route('/stock-out', methods=['GET','POST'])
    @login_required
    def stock_out():
        if request.method == 'POST':
            try:
                pid, qty = integer('product_id'), integer('quantity')
                token = request.form.get('token','')
                if len(token) != 64:
                    raise ValueError('Phiếu không hợp lệ. Vui lòng tải lại trang.')
                if Movement.query.filter_by(token=token).first():
                    flash('Phiếu này đã được ghi nhận.', 'info')
                    return redirect(url_for('stock_out'))
                # Conditional UPDATE serializes concurrent exports; balance and ledger commit together.
                result = db.session.execute(update(Product).where(Product.id == pid, Product.stock >= qty).values(stock=Product.stock-qty))
                if result.rowcount != 1:
                    raise ValueError('Không đủ tồn kho hoặc phụ kiện không tồn tại. Vui lòng kiểm tra lại.')
                db.session.add(Movement(product_id=pid, user_id=g.user.id, kind='out', quantity=qty, token=token, note=request.form.get('note','').strip()[:250]))
                db.session.commit()
                flash(f'Đã xuất kho {qty} phụ kiện.', 'success')
                return redirect(url_for('stock_out'))
            except ValueError as e:
                db.session.rollback()
                flash(str(e), 'error')
            except IntegrityError:
                db.session.rollback()
                flash('Phiếu đã được xử lý. Tồn kho không bị trừ thêm.', 'info')
        q = request.args.get('q','').strip()[:120]
        products = search_products(q).paginate(page=request.args.get('page',1,type=int), per_page=12, error_out=False)
        return render_template('stock_out.html', products=products, q=q, token=secrets.token_hex(32))

    @app.post('/products/<int:pid>/minimum')
    @admin_required
    def minimum(pid):
        product = db.get_or_404(Product, pid)
        try:
            product.minimum = integer('minimum', 0)
            db.session.commit()
            flash('Đã cập nhật mức tồn tối thiểu.', 'success')
        except ValueError as e:
            flash(str(e),'error')
        return redirect(url_for('dashboard'))

    @app.get('/reports')
    @admin_required
    def reports():
        try:
            mode, value, start, end, label = period_bounds(request.args)
        except (ValueError, OverflowError):
            flash('Ngày hoặc kỳ báo cáo không hợp lệ.', 'error')
            return redirect(url_for('reports'))
        kind = request.args.get('kind', '')
        query = Movement.query.filter(Movement.created_at >= start, Movement.created_at < end)
        if kind in ('in','out'):
            query = query.filter_by(kind=kind)
        totals = dict(db.session.query(Movement.kind,func.sum(Movement.quantity)).filter(Movement.created_at >= start, Movement.created_at < end).group_by(Movement.kind).all())
        if request.args.get('download') == 'csv':
            stream = io.StringIO()
            writer = csv.writer(stream)
            writer.writerow(['Mã phiếu','Thời gian (VN)','Loại','Phụ kiện','Màu','Dòng xe','Số lượng','Người thực hiện','Ghi chú'])
            def safe(v):
                s = str(v)
                return "'"+s if s.lstrip().startswith(('=','+','-','@')) else s
            for m in query.order_by(Movement.created_at.desc(),Movement.id.desc()).yield_per(500):
                writer.writerow([m.id,m.created_at.strftime('%d/%m/%Y %H:%M'), 'Nhập' if m.kind=='in' else 'Xuất',safe(m.product.name),safe(m.product.color),safe(m.product.vehicle),m.quantity,safe(m.user.name),safe(m.note)])
            return Response('\ufeff'+stream.getvalue(), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition':f'attachment; filename="bao-cao-{value.isoformat()}.csv"'})
        movements = query.order_by(Movement.created_at.desc(),Movement.id.desc()).paginate(page=request.args.get('page',1,type=int),per_page=30,error_out=False)
        # Current inventory, deliberately independent of movement period.
        grouped = db.session.query(Product.name,func.sum(Product.stock)).group_by(Product.name).order_by(func.sum(Product.stock).desc()).all()
        maxstock = max([r[1] for r in grouped] or [1]) or 1
        lows = Product.query.filter(Product.stock <= Product.minimum).order_by(Product.stock, Product.name).all()
        return render_template('reports.html', movements=movements, mode=mode, value=value, label=label, kind=kind, totals=totals, grouped=grouped, maxstock=maxstock, lows=lows)

    @app.route('/users', methods=['GET','POST'])
    @admin_required
    def users():
        if request.method == 'POST':
            try:
                username = text_field('username',50).lower()
                if not re.fullmatch(r'[a-z0-9_.-]{3,50}',username):
                    raise ValueError('Tên đăng nhập: 3–50 ký tự, chỉ dùng a-z, 0-9, dấu chấm, gạch dưới hoặc gạch ngang.')
                name = text_field('name',100)
                password = request.form.get('password','')
                if not 10 <= len(password) <= 128:
                    raise ValueError('Mật khẩu cần từ 10 đến 128 ký tự.')
                role = request.form.get('role','staff')
                if role not in ('admin','staff'):
                    raise ValueError('Quyền tài khoản không hợp lệ.')
                if User.query.filter_by(username=username).first():
                    raise ValueError('Tên đăng nhập đã tồn tại; hãy dùng tên khác.')
                db.session.add(User(username=username,name=name,password_hash=generate_password_hash(password),role=role))
                db.session.commit()
                flash('Đã tạo tài khoản.', 'success')
                return redirect(url_for('users'))
            except ValueError as e:
                flash(str(e),'error')
            except IntegrityError:
                db.session.rollback()
                flash('Tên đăng nhập đã tồn tại.', 'error')
        return render_template('users.html', users=User.query.filter_by(active=True).order_by(User.id).all())

    @app.post('/users/<int:uid>/delete')
    @admin_required
    def delete_user(uid):
        actor_id = g.user.id
        db.session.rollback()
        if db.engine.dialect.name == 'sqlite':
            db.session.execute(text('BEGIN IMMEDIATE'))
        # All admin removals acquire locks in a fixed order, then recheck the actor.
        admins = User.query.filter_by(role='admin',active=True).order_by(User.id).with_for_update().all()
        actor = db.session.get(User, actor_id)
        user = db.get_or_404(User, uid)
        if not actor or not actor.active:
            db.session.rollback()
            abort(403)
        if uid == actor_id:
            flash('Không thể xóa tài khoản đang đăng nhập.', 'error')
            db.session.rollback()
        elif user.role == 'admin' and len(admins) <= 1:
            flash('Phải giữ lại ít nhất một quản trị viên.', 'error')
            db.session.rollback()
        else:
            user.active = False
            db.session.commit()
            flash('Đã xóa quyền truy cập của tài khoản. Lịch sử xuất nhập được giữ lại.', 'success')
        return redirect(url_for('users'))

    @app.route('/password', methods=['GET','POST'])
    @login_required
    def password():
        if request.method == 'POST':
            new = request.form.get('password','')
            if not check_password_hash(g.user.password_hash,request.form.get('current','')):
                flash('Mật khẩu hiện tại không đúng.','error')
            elif not 10 <= len(new) <= 128:
                flash('Mật khẩu mới cần từ 10 đến 128 ký tự.','error')
            elif new != request.form.get('confirm',''):
                flash('Xác nhận mật khẩu không khớp.','error')
            else:
                g.user.password_hash = generate_password_hash(new)
                db.session.commit()
                flash('Đã đổi mật khẩu.','success')
                return redirect(url_for('dashboard'))
        return render_template('password.html')

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(429)
    def error(e):
        messages = {400:'Phiên biểu mẫu đã hết hạn hoặc dữ liệu không hợp lệ. Hãy tải lại trang.',403:'Bạn không có quyền truy cập trang này.',404:'Không tìm thấy trang hoặc dữ liệu.',429:'Bạn thử đăng nhập quá nhiều lần. Vui lòng đợi một phút.'}
        return render_template('error.html',code=e.code,message=messages.get(e.code,'Có lỗi xảy ra.')),e.code

    @app.cli.command('init-db')
    def init_db():
        """Create schema and bootstrap the first admin from environment variables."""
        db.create_all()
        if User.query.filter_by(role='admin',active=True).first():
            click.echo('Database sẵn sàng. Đã có admin; không thay đổi mật khẩu.')
            return
        username = os.getenv('ADMIN_USERNAME','admin').strip().lower()
        password = os.getenv('ADMIN_PASSWORD','')
        if not re.fullmatch(r'[a-z0-9_.-]{3,50}',username) or not 10 <= len(password) <= 128:
            raise click.ClickException('Cần ADMIN_USERNAME hợp lệ và ADMIN_PASSWORD dài 10–128 ký tự.')
        db.session.add(User(username=username,name='Quản trị Khải Oanh',role='admin',password_hash=generate_password_hash(password)))
        db.session.commit()
        click.echo('Đã khởi tạo database và tài khoản admin.')

    @app.cli.command('reset-password')
    @click.argument('username')
    @click.password_option(confirmation_prompt=True)
    def reset_password(username,password):
        user = User.query.filter_by(username=username.lower(),active=True).first()
        if not user or not 10 <= len(password) <= 128:
            raise click.ClickException('Tài khoản không tồn tại hoặc mật khẩu không đủ 10–128 ký tự.')
        user.password_hash = generate_password_hash(password)
        db.session.commit()
        click.echo('Đã đặt lại mật khẩu.')

    return app


app = create_app()
if __name__ == '__main__':
    app.run(host='127.0.0.1',port=5000,debug=False)
