import os, tempfile
os.environ['EVENTOPS_DATA_DIR']=tempfile.mkdtemp(prefix='eventops-tests-')
os.environ['EVENTOPS_ALLOWED_HOSTS']='testserver,localhost,127.0.0.1'
import pytest
from fastapi.testclient import TestClient
from app import main as m

PASSWORD='TestsOnly!Password2026'
@pytest.fixture(autouse=True)
def clean():
    m.initialize()
    with m.db(True) as c:
        for table in ['audit','certificates','task_dependencies','tasks','announcements','agenda','resources','feedback','attendance','registrations','sessions','events','users','settings']:
            c.execute('DELETE FROM '+table)
    m._rate.clear()

def user(name='Participant',role='participant'):
    i=m.uid(); address=i[:8]+'@example.test'
    with m.db(True) as c:c.execute('INSERT INTO users VALUES(?,?,?,?,?,?)',(i,name,address,m.password_hash(PASSWORD),role,m.now()))
    client=TestClient(m.app)
    response=client.post('/api/auth/login',json={'email':address,'password':PASSWORD});assert response.status_code==200,response.text
    client.headers['X-CSRF-Token']=response.json()['csrf']
    return client,i

def event(client,capacity=10,feedback=True):
    response=client.post('/api/events',json={'title':'Test Summit','description':'Testing','venue':'Test Hall','start':'2030-01-05T09:00:00Z','end':'2030-01-05T17:00:00Z','capacity':capacity,'feedback_required':feedback})
    assert response.status_code==201,response.text
    return response.json()['id']
def register(client,e):
    r=client.post(f'/api/events/{e}/register',json={'preferences':'Vegetarian'});assert r.status_code==201,r.text;return r.json()
def checkin(admin,e,ticket):
    r=admin.post(f'/api/events/{e}/checkin',json={'ticket':ticket});assert r.status_code==200,r.text;return r.json()

def test_password_hashing_and_session_cookie():
    hashed=m.password_hash(PASSWORD);assert hashed!=PASSWORD;assert m.password_ok(PASSWORD,hashed);assert not m.password_ok('wrong',hashed)
    c,_=user();cookie=c.cookies.get(m.COOKIE);assert cookie
    with m.db() as db:row=db.execute('SELECT token_hash FROM sessions').fetchone();assert cookie!=row[0]
    assert c.get('/api/auth/me').status_code==200
    assert c.post('/api/auth/logout').status_code==200
    assert c.get('/api/auth/me').status_code==401

def test_signup_cannot_choose_organizer_role():
    c=TestClient(m.app)
    r=c.post('/api/auth/signup',json={'name':'New Guest','email':'new@example.test','password':PASSWORD,'role':'organizer'});assert r.status_code==422
    r=c.post('/api/auth/signup',json={'name':'New Guest','email':'new@example.test','password':PASSWORD});assert r.status_code==201;assert r.json()['role']=='participant'
    assert c.post('/api/auth/signup',json={'name':'Duplicate','email':'new@example.test','password':PASSWORD}).status_code==409

def test_csrf_origin_and_host_boundaries():
    c,_=user(role='organizer');saved=c.headers.pop('X-CSRF-Token');assert c.post('/api/auth/logout').status_code==403
    c.headers['X-CSRF-Token']=saved
    assert c.post('/api/auth/logout',headers={'Origin':'https://evil.example'}).status_code==403
    assert c.post('/api/auth/logout',headers={'Sec-Fetch-Site':'cross-site'}).status_code==403
    assert c.get('/api/health',headers={'Host':'evil.example'}).status_code==400
    r=c.get('/api/auth/me');assert r.headers['cache-control']=='no-store';assert "frame-ancestors 'none'" in r.headers['content-security-policy']

def test_capacity_waitlist_and_promotion():
    a,_=user(role='organizer');e=event(a,1);p,_=user();q,_=user()
    r=register(p,e);s=register(q,e);assert r['status']=='confirmed';assert s['status']=='waitlisted'
    assert p.post(f'/api/events/{e}/register',json={}).status_code==409
    assert q.get(f'/api/events/{e}/ticket.png').status_code==403
    assert p.post(f'/api/events/{e}/cancel').json()['promoted']
    assert q.get(f'/api/events/{e}').json()['registration']['status']=='confirmed'
    assert a.get(f'/api/events/{e}/analytics').json()['confirmed']==1

def test_duplicate_checkin_is_idempotent_and_cancel_blocked():
    a,_=user(role='organizer');e=event(a);p,_=user();r=register(p,e)
    result=checkin(a,e,'eventops:'+r['ticket']);assert not result['already_checked_in']
    assert checkin(a,e,r['ticket'])['already_checked_in']
    assert a.get(f'/api/events/{e}/analytics').json()['checked_in']==1
    assert p.post(f'/api/events/{e}/cancel').status_code==409
    assert p.get(f'/api/events/{e}/ticket.png').content.startswith(b'\x89PNG')

def test_feedback_requires_attendance_and_is_unique():
    a,_=user(role='organizer');e=event(a);p,_=user();r=register(p,e)
    body={'rating':5,'comment':'Well organized'}
    assert p.post(f'/api/events/{e}/feedback',json=body).status_code==409
    checkin(a,e,r['ticket']);assert p.post(f'/api/events/{e}/feedback',json=body).status_code==201
    assert p.post(f'/api/events/{e}/feedback',json=body).status_code==409
    report=a.get(f'/api/events/{e}/feedback').json();assert report['count']==1;assert report['average']==5
    assert 'email' not in report['items'][0] and 'name' not in report['items'][0]

def test_organizer_and_member_authorization():
    a,_=user(role='organizer');b,_=user(role='organizer');e=event(a);p,_=user()
    for route in ['registrations','analytics','audit','feedback','certificates','team']:
        assert p.get(f'/api/events/{e}/{route}').status_code==403
        assert b.get(f'/api/events/{e}/{route}').status_code==403
    assert p.get(f'/api/events/{e}/resources').status_code==403
    assert p.post('/api/events',json={'title':'Invalid','venue':'Hall','start':'2030-01-05T09:00:00Z','end':'2030-01-05T17:00:00Z','capacity':2}).status_code==403
    register(p,e);assert p.get(f'/api/events/{e}/resources').status_code==200

def test_safe_resource_links_and_files():
    a,_=user(role='organizer');e=event(a);p,_=user();q,_=user();register(p,e)
    assert a.post(f'/api/events/{e}/resources',json={'title':'Bad link','url':'javascript:alert(1)'}).status_code==422
    assert a.post(f'/api/events/{e}/resources',json={'title':'Good link','url':'https://example.org/reference'}).status_code==201
    r=a.post(f'/api/events/{e}/resources/upload',data={'title':'Read me'},files={'file':('../../evil.txt',b'Workshop notes','text/plain')});assert r.status_code==201,r.text
    rid=r.json()['id'];assert p.get(f'/api/resources/{rid}/download').content==b'Workshop notes'
    assert q.get(f'/api/resources/{rid}/download').status_code==403
    assert p.post(f'/api/events/{e}/resources/upload',data={'title':'Unauthorized'},files={'file':('x.txt',b'x','text/plain')}).status_code==403
    assert a.post(f'/api/events/{e}/resources/upload',data={'title':'Executable'},files={'file':('x.html',b'<script>1</script>','text/html')}).status_code==422
    assert a.post(f'/api/events/{e}/resources/upload',data={'title':'Fake PDF'},files={'file':('x.pdf',b'not a pdf','application/pdf')}).status_code==422

def test_task_dependencies_and_assignee_permissions():
    a,aid=user(role='organizer');e=event(a);p,pid=user();q,qid=user();register(p,e);register(q,e)
    task={'title':'Prepare venue','due':'2030-01-04T10:00:00Z','assignee_id':pid}
    first=a.post(f'/api/events/{e}/tasks',json=task);assert first.status_code==201;one=first.json()['id']
    two=a.post(f'/api/events/{e}/tasks',json={**task,'title':'Open registration desk','dependencies':[one]}).json()['id']
    assert p.patch('/api/tasks/'+two,json={'status':'done'}).status_code==409
    assert q.patch('/api/tasks/'+one,json={'status':'done'}).status_code==403
    assert p.patch('/api/tasks/'+one,json={'status':'done'}).status_code==200
    assert p.patch('/api/tasks/'+two,json={'status':'done'}).status_code==200
    assert p.patch('/api/tasks/'+one,json={'status':'todo'}).status_code==409
    assert len(q.get(f'/api/events/{e}/tasks').json())==0
    other=event(a);assert a.post(f'/api/events/{other}/tasks',json={**task,'assignee_id':aid,'dependencies':[one]}).status_code==422

def test_certificate_eligibility_pdf_verify_and_revocation():
    a,_=user(role='organizer');e=event(a);p,pid=user('Taylor Guest');q,_=user();r=register(p,e)
    assert a.post(f'/api/events/{e}/certificates/{pid}').status_code==409
    checkin(a,e,r['ticket']);assert a.post(f'/api/events/{e}/certificates/{pid}').status_code==409
    p.post(f'/api/events/{e}/feedback',json={'rating':4,'comment':'Useful'})
    cid=a.post(f'/api/events/{e}/certificates/{pid}').json()['id']
    assert a.post(f'/api/events/{e}/certificates/{pid}').json()['id']==cid
    pdf=p.get('/api/certificates/'+cid+'/download');assert pdf.status_code==200;assert pdf.content.startswith(b'%PDF-')
    assert q.get('/api/certificates/'+cid+'/download').status_code==403
    with m.db() as c:token=c.execute('SELECT verify_token FROM certificates WHERE id=?',(cid,)).fetchone()[0]
    public=TestClient(m.app);r=public.get('/api/verify/'+token);assert r.json()['valid'];assert 'email' not in r.json()
    assert p.post('/api/certificates/'+cid+'/revoke').status_code==403
    assert a.post('/api/certificates/'+cid+'/revoke').status_code==200
    assert not public.get('/api/verify/'+token).json()['valid'];assert p.get('/api/certificates/'+cid+'/download').status_code==410

def test_bulk_issue_skips_ineligible_and_is_idempotent():
    a,_=user(role='organizer');e=event(a,feedback=False);p,pid=user();q,_=user();r=register(p,e);register(q,e);checkin(a,e,r['ticket'])
    r=a.post(f'/api/events/{e}/certificates/batch/issue');assert r.status_code==200,r.text
    assert len(r.json()['issued'])==1 and len(r.json()['skipped'])==1
    assert a.post(f'/api/events/{e}/certificates/batch/issue').json()['issued']==r.json()['issued']

def test_agenda_boundaries_and_timezone_validation():
    a,_=user(role='organizer');e=event(a)
    data={'title':'Welcome','speaker':'Host','start':'2030-01-05T09:00:00Z','end':'2030-01-05T10:00:00Z'}
    assert a.post(f'/api/events/{e}/agenda',json=data).status_code==201
    assert a.post(f'/api/events/{e}/agenda',json={**data,'end':'2030-01-06T10:00:00Z'}).status_code==422
    assert a.post(f'/api/events/{e}/agenda',json={**data,'start':'2030-01-05T09:00:00'}).status_code==422

def test_csv_formula_escape_and_audit():
    a,_=user(role='organizer');e=event(a);p,_=user('=HYPERLINK("https://evil.test")');register(p,e)
    result=a.get(f'/api/events/{e}/export.csv');assert result.status_code==200;assert "'=HYPERLINK" in result.text
    assert p.get(f'/api/events/{e}/export.csv').status_code==403
    actions=[x['action'] for x in a.get(f'/api/events/{e}/audit').json()];assert 'event.create' in actions and 'registration.create' in actions

def test_rate_limit_and_request_size():
    c=TestClient(m.app)
    for _ in range(15):assert c.post('/api/auth/login',json={'email':'missing@example.test','password':'wrong'}).status_code==401
    assert c.post('/api/auth/login',json={'email':'missing@example.test','password':'wrong'}).status_code==429
    assert c.post('/api/auth/login',content=b'',headers={'Content-Length':str(12*1024*1024)}).status_code==413

def test_static_files_never_expose_database_or_uploads():
    c=TestClient(m.app)
    assert c.get('/').status_code==200
    assert c.get('/.data/eventops.sqlite3').status_code==404
    assert c.get('/uploads/x.txt').status_code==404

def test_draft_events_hidden_from_other_users():
    a,_=user(role='organizer');p,_=user()
    body={'title':'Private draft','venue':'Hall','start':'2030-01-05T09:00:00Z','end':'2030-01-05T17:00:00Z','capacity':5,'status':'draft'}
    e=a.post('/api/events',json=body).json()['id']
    assert all(x['id']!=e for x in p.get('/api/events').json())
    assert p.get('/api/events/'+e).status_code==404
    assert p.post(f'/api/events/{e}/register',json={}).status_code==409
