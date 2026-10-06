import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from werkzeug.security import generate_password_hash
from app import create_app, db, User, Product, Movement, period_bounds


@pytest.fixture()
def app(tmp_path):
    app = create_app({'TESTING':True,'SECRET_KEY':'test-key','SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(tmp_path/'test.db'), 'WTF_CSRF_ENABLED':False,'RATELIMIT_ENABLED':False})
    with app.app_context():
        db.create_all()
        db.session.add_all([User(username='admin',name='Admin',role='admin',password_hash=generate_password_hash('AdminPass123!')),User(username='staff',name='Nhân viên',role='staff',password_hash=generate_password_hash('StaffPass123!'))])
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def auth(app,username='admin'):
    client=app.test_client()
    client.post('/login',data={'username':username,'password':'AdminPass123!' if username=='admin' else 'StaffPass123!'})
    return client


def enter(client,quantity=10,**extra):
    data=dict(name='Gương chiếu hậu',color='Đen',vehicle='Wave',quantity=str(quantity),token=secrets.token_hex(32))
    data.update(extra)
    return client.post('/stock-in',data=data,follow_redirects=True)


def test_pages_login_and_role(app):
    assert app.test_client().get('/').status_code==302
    assert app.test_client().get('/login').status_code==200
    admin=auth(app)
    for route in ['/', '/stock-in','/stock-out','/reports','/users','/password','/health']:
        assert admin.get(route).status_code==200,route
    staff=auth(app,'staff')
    assert staff.get('/reports').status_code==403
    assert staff.get('/users').status_code==403
    assert staff.post('/users/1/delete').status_code==403


def test_stock_ledger_variants_and_validation(app):
    c=auth(app)
    enter(c,10)
    enter(c,5)
    enter(c,3,color='Đỏ')
    with app.app_context():
        p=Product.query.filter_by(color='Đen').one()
        pid=p.id
        assert p.stock==15
        assert Product.query.count()==2
    rejected=c.post('/stock-out',data={'product_id':pid,'quantity':16,'token':secrets.token_hex(32)},follow_redirects=True)
    assert 'Không đủ tồn kho' in rejected.text
    for invalid in ['0','-3','1.5','NaN','100000001']:
        enter(c,invalid)
    c.post('/stock-out',data={'product_id':pid,'quantity':7,'token':secrets.token_hex(32)})
    with app.app_context():
        assert db.session.get(Product,pid).stock==8
        assert Movement.query.count()==4
        balance=sum(m.quantity*(1 if m.kind=='in' else -1) for m in Movement.query.filter_by(product_id=pid))
        assert balance==8
    assert 'Gương chiếu hậu' in c.get('/stock-out?q=Wave').text
    assert 'Không tìm thấy' in c.get('/stock-out?q=XYZ').text


def test_idempotency(app):
    c=auth(app)
    token=secrets.token_hex(32)
    enter(c,10,token=token)
    enter(c,10,token=token)
    with app.app_context():
        pid=Product.query.one().id
        assert Product.query.one().stock==10
    data={'product_id':pid,'quantity':3,'token':secrets.token_hex(32)}
    c.post('/stock-out',data=data)
    c.post('/stock-out',data=data)
    with app.app_context():
        assert Product.query.one().stock==7
        assert Movement.query.count()==2


def test_concurrent_exports(app):
    c=auth(app)
    enter(c,10)
    with app.app_context():
        pid=Product.query.one().id
    c1,c2=auth(app),auth(app)
    def export(client):
        return client.post('/stock-out',data={'product_id':pid,'quantity':7,'token':secrets.token_hex(32)},follow_redirects=True).text
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(export,[c1,c2]))
    assert sum('Đã xuất kho 7' in r for r in results)==1
    with app.app_context():
        assert Product.query.one().stock==3
        assert Movement.query.filter_by(kind='out').count()==1


def test_user_delete_revokes_existing_session_keeps_history(app):
    admin=auth(app)
    staff=auth(app,'staff')
    enter(staff,4)
    admin.post('/users/2/delete')
    assert staff.get('/').status_code==302
    with app.app_context():
        assert not db.session.get(User,2).active
        assert Movement.query.one().user.name=='Nhân viên'
    admin.post('/users/1/delete')
    with app.app_context():
        assert db.session.get(User,1).active
    admin.post('/users',data={'name':'Admin thứ hai','username':'admin2','password':'AnotherPass123!','role':'admin'})
    admin.post('/users/3/delete')
    with app.app_context():
        assert not db.session.get(User,3).active
        assert User.query.filter_by(active=True,role='admin').count()==1


def test_reports_boundaries_and_csv(app):
    c=auth(app)
    enter(c,8,note='=HYPERLINK("bad")')
    with app.app_context():
        Movement.query.one().created_at=datetime(2026,3,31,23,59)
        db.session.commit()
    r=c.get('/reports?period=quarter&date=2026-02-01')
    assert 'Quý 1/2026' in r.text and '#00001' in r.text
    r=c.get('/reports?period=quarter&date=2026-04-01')
    assert '#00001' not in r.text
    csv=c.get('/reports?period=month&date=2026-03-01&download=csv')
    assert csv.status_code==200 and "'=HYPERLINK" in csv.text
    assert c.get('/reports?date=bad').status_code==302
    mode,day,start,end,label=period_bounds({'period':'quarter','date':'2026-12-31'})
    assert start==datetime(2026,10,1) and end==datetime(2027,1,1)


def test_csrf_and_password_security(app):
    app.config['WTF_CSRF_ENABLED']=True
    c=app.test_client()
    assert c.post('/login',data={'username':'admin','password':'AdminPass123!'}).status_code==400
    with app.app_context():
        assert db.session.get(User,1).password_hash!='AdminPass123!'


def test_initialize_does_not_reset_admin(app,monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD','DifferentPass123!')
    runner=app.test_cli_runner()
    assert runner.invoke(args=['init-db']).exit_code==0
    assert auth(app).get('/').status_code==200
