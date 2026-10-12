"""EventOps: seven event-management modules with a single authorization boundary."""
from __future__ import annotations
import csv, hashlib, hmac, io, json, os, re, secrets, sqlite3, threading, time, uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import qrcode
from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from starlette.middleware.trustedhost import TrustedHostMiddleware

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv('EVENTOPS_DATA_DIR', str(ROOT / '.data'))).resolve()
BASE_URL = os.getenv('EVENTOPS_BASE_URL', 'http://localhost:8000').rstrip('/')
SECURE = os.getenv('EVENTOPS_SECURE_COOKIES', '0') == '1'
SESSION_TTL = 60 * 60 * 12
COOKIE = 'eventops_session'

SCHEMA = '''
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES(1);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,name TEXT NOT NULL,email TEXT NOT NULL UNIQUE,password TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('organizer','participant')),created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),csrf TEXT NOT NULL,expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL,venue TEXT NOT NULL,start TEXT NOT NULL,end TEXT NOT NULL,capacity INTEGER NOT NULL CHECK(capacity>0),status TEXT NOT NULL DEFAULT 'published' CHECK(status IN ('draft','published','closed')),feedback_required INTEGER NOT NULL DEFAULT 1,owner_id TEXT NOT NULL REFERENCES users(id),created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS registrations(id TEXT PRIMARY KEY,event_id TEXT NOT NULL REFERENCES events(id),user_id TEXT NOT NULL REFERENCES users(id),status TEXT NOT NULL CHECK(status IN ('confirmed','waitlisted','cancelled')),preferences TEXT NOT NULL,ticket TEXT NOT NULL UNIQUE,created TEXT NOT NULL,UNIQUE(event_id,user_id));
CREATE INDEX IF NOT EXISTS registration_queue ON registrations(event_id,status,created,id);
CREATE TABLE IF NOT EXISTS attendance(id TEXT PRIMARY KEY,registration_id TEXT NOT NULL UNIQUE REFERENCES registrations(id),checked_by TEXT NOT NULL REFERENCES users(id),method TEXT NOT NULL,created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feedback(id TEXT PRIMARY KEY,event_id TEXT NOT NULL REFERENCES events(id),user_id TEXT NOT NULL REFERENCES users(id),rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),comment TEXT NOT NULL,created TEXT NOT NULL,UNIQUE(event_id,user_id));
CREATE TABLE IF NOT EXISTS resources(id TEXT PRIMARY KEY,event_id TEXT NOT NULL REFERENCES events(id),title TEXT NOT NULL,kind TEXT NOT NULL CHECK(kind IN ('link','file')),url TEXT,path TEXT,mime TEXT,size INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agenda(id TEXT PRIMARY KEY,event_id TEXT NOT NULL REFERENCES events(id),title TEXT NOT NULL,speaker TEXT NOT NULL,start TEXT NOT NULL,end TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS announcements(id TEXT PRIMARY KEY,event_id TEXT NOT NULL REFERENCES events(id),title TEXT NOT NULL,body TEXT NOT NULL,created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,event_id TEXT NOT NULL REFERENCES events(id),title TEXT NOT NULL,description TEXT NOT NULL,assignee_id TEXT REFERENCES users(id),due TEXT NOT NULL,priority TEXT NOT NULL CHECK(priority IN ('low','normal','high')),status TEXT NOT NULL DEFAULT 'todo' CHECK(status IN ('todo','doing','done')),created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS task_dependencies(task_id TEXT NOT NULL REFERENCES tasks(id),depends_on TEXT NOT NULL REFERENCES tasks(id),PRIMARY KEY(task_id,depends_on),CHECK(task_id!=depends_on));
CREATE TABLE IF NOT EXISTS certificates(id TEXT PRIMARY KEY,event_id TEXT NOT NULL REFERENCES events(id),user_id TEXT NOT NULL REFERENCES users(id),verify_token TEXT NOT NULL UNIQUE,revoked INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL,UNIQUE(event_id,user_id));
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,actor_id TEXT,event_id TEXT,action TEXT NOT NULL,detail TEXT NOT NULL,created TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS audit_event ON audit(event_id,id);
'''

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def uid(): return uuid.uuid4().hex

def password_hash(value, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', value.encode(), bytes.fromhex(salt), 310000).hex()
    return f'pbkdf2_sha256$310000${salt}${digest}'

def password_ok(value, stored):
    try:
        algorithm, iterations, salt, digest = stored.split('$')
        if algorithm != 'pbkdf2_sha256': return False
        actual = hashlib.pbkdf2_hmac('sha256', value.encode(), bytes.fromhex(salt), int(iterations)).hex()
        return hmac.compare_digest(actual, digest)
    except (ValueError, TypeError): return False

DUMMY_PASSWORD_HASH = password_hash('dummy-password', '00'*16)

@contextmanager
def db(write=False):
    c = sqlite3.connect(DATA / 'eventops.sqlite3', timeout=15)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=15000')
    try:
        if write: c.execute('BEGIN IMMEDIATE')
        yield c
        c.commit()
    except Exception:
        c.rollback(); raise
    finally: c.close()

def initialize():
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / 'uploads').mkdir(exist_ok=True)
    with db() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript(SCHEMA)
        demo = c.execute("SELECT value FROM settings WHERE key='demo'").fetchone()
        if SECURE and demo and demo['value'] == '1':
            raise RuntimeError('Demo database is forbidden with secure production cookies. Use a fresh data directory.')

@asynccontextmanager
async def lifespan(app):
    initialize(); yield

app = FastAPI(title='EventOps Pro', version='1.0.0', lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=os.getenv('EVENTOPS_ALLOWED_HOSTS','localhost,127.0.0.1').split(','))

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
class Signup(Input):
    name: str = Field(min_length=2,max_length=80)
    email: str = Field(min_length=5,max_length=200)
    password: str = Field(min_length=12,max_length=128)
class Login(Input):
    email: str = Field(min_length=5,max_length=200)
    password: str = Field(min_length=1,max_length=128)
class EventInput(Input):
    title: str = Field(min_length=3,max_length=150)
    description: str = Field(default='',max_length=3000)
    venue: str = Field(min_length=2,max_length=160)
    start: str
    end: str
    capacity: int = Field(ge=1,le=100000)
    status: str = 'published'
    feedback_required: bool = True
class RegistrationInput(Input):
    preferences: str = Field(default='',max_length=600)
class CheckinInput(Input):
    ticket: str = Field(min_length=10,max_length=200)
    method: str = 'manual'
class FeedbackInput(Input):
    rating: int = Field(ge=1,le=5)
    comment: str = Field(default='',max_length=3000)
class ResourceInput(Input):
    title: str = Field(min_length=2,max_length=150)
    url: str = Field(max_length=2000)
class TaskInput(Input):
    title: str = Field(min_length=2,max_length=150)
    description: str = Field(default='',max_length=2000)
    assignee_id: str | None = None
    due: str
    priority: str = 'normal'
    dependencies: list[str] = Field(default_factory=list,max_length=20)
class TaskStatus(Input):
    status: str
class AnnouncementInput(Input):
    title: str = Field(min_length=2,max_length=150)
    body: str = Field(min_length=2,max_length=3000)
class AgendaInput(Input):
    title: str = Field(min_length=2,max_length=150)
    speaker: str = Field(default='',max_length=100)
    start: str
    end: str

_rate = defaultdict(deque)
_rate_lock = threading.Lock()
def throttle(key, maximum=15, window=300):
    with _rate_lock:
        stamp = time.monotonic()
        if len(_rate)>10000: _rate.clear()
        q = _rate[key]
        while q and q[0] < stamp-window: q.popleft()
        if len(q)>=maximum: raise HTTPException(429,'Too many attempts. Try again later.',headers={'Retry-After':str(window)})
        q.append(stamp)

@app.middleware('http')
async def boundaries(request: Request, call_next):
    if request.method in ('POST','PUT','PATCH','DELETE'):
        origin = request.headers.get('origin')
        if origin and origin.rstrip('/') != BASE_URL:
            return JSONResponse({'detail':'Untrusted request origin'},403)
        if request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail':'Cross-site writes are not allowed'},403)
    if request.method in ('POST','PUT','PATCH','DELETE') and ('content-length' not in request.headers or request.headers.get('transfer-encoding')):
        return JSONResponse({'detail':'Content-Length is required; chunked uploads are not supported'},411)
    length = request.headers.get('content-length','0')
    try:
        if int(length)>11*1024*1024: return JSONResponse({'detail':'Request too large'},413)
    except ValueError: return JSONResponse({'detail':'Invalid content length'},400)
    response = await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Permissions-Policy']='camera=(self), microphone=(), geolocation=()'
    response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    if request.url.path.startswith('/api'):
        response.headers['Cache-Control']='no-store'
    if SECURE: response.headers['Strict-Transport-Security']='max-age=31536000'
    return response

@app.exception_handler(sqlite3.OperationalError)
async def sqlite_error(request, exc):
    return JSONResponse({'detail':'Database temporarily unavailable. Please retry.'},503)

def get_user(request: Request):
    token = request.cookies.get(COOKIE,'')
    if not token: raise HTTPException(401,'Sign in to continue')
    with db() as c:
        row = c.execute('SELECT u.id,u.name,u.email,u.role,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?',(hashlib.sha256(token.encode()).hexdigest(),int(time.time()))).fetchone()
    if not row: raise HTTPException(401,'Session expired. Sign in again.')
    if request.method not in ('GET','HEAD','OPTIONS') and not hmac.compare_digest(request.headers.get('x-csrf-token',''),row['csrf']):
        raise HTTPException(403,'Invalid CSRF token')
    return dict(row)

def log(c, user, event_id, action, detail=''):
    c.execute('INSERT INTO audit(actor_id,event_id,action,detail,created) VALUES(?,?,?,?,?)',(user['id'],event_id,action,str(detail)[:1000],now()))
def event(c, event_id):
    row = c.execute('SELECT * FROM events WHERE id=?',(event_id,)).fetchone()
    if not row: raise HTTPException(404,'Event not found')
    return row

def owner(c, event_id, user):
    e = event(c,event_id)
    if user['role']!='organizer' or e['owner_id']!=user['id']: raise HTTPException(403,'Only this event’s organizer can perform this action')
    return e

def member(c, event_id, user):
    e = event(c,event_id)
    if user['id']==e['owner_id']: return e
    row=c.execute("SELECT status FROM registrations WHERE event_id=? AND user_id=? AND status='confirmed'",(event_id,user['id'])).fetchone()
    if not row: raise HTTPException(403,'Confirmed registration required')
    return e

def iso(value):
    try:
        d = datetime.fromisoformat(value.replace('Z','+00:00'))
        if d.tzinfo is None: raise ValueError()
        return d.astimezone(timezone.utc).isoformat(timespec='seconds')
    except ValueError: raise HTTPException(422,'Dates must include an explicit timezone')

def email(value):
    value=value.lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value): raise HTTPException(422,'Enter a valid email address')
    return value

def session(c,user_id,response):
    token=secrets.token_urlsafe(40); csrf=secrets.token_urlsafe(32)
    c.execute('DELETE FROM sessions WHERE expires<=?',(int(time.time()),))
    c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user_id,csrf,int(time.time())+SESSION_TTL))
    response.set_cookie(COOKIE,token,max_age=SESSION_TTL,httponly=True,secure=SECURE,samesite='lax',path='/')
    u=dict(c.execute('SELECT id,name,email,role FROM users WHERE id=?',(user_id,)).fetchone());u['csrf']=csrf
    return u

@app.get('/api/health')
def health(): return {'status':'ok','version':'1.0.0'}
@app.post('/api/auth/signup',status_code=201)
def signup(body: Signup, request: Request, response: Response):
    throttle('signup:'+request.client.host,5,600)
    with db(True) as c:
        try:
            user_id=uid();c.execute('INSERT INTO users VALUES(?,?,?,?,?,?)',(user_id,body.name,email(body.email),password_hash(body.password),'participant',now()))
        except sqlite3.IntegrityError: raise HTTPException(409,'An account with that email already exists')
        return session(c,user_id,response)
@app.post('/api/auth/login')
def login(body: Login, request: Request,response: Response):
    throttle('login:'+request.client.host)
    with db(True) as c:
        user=c.execute('SELECT * FROM users WHERE email=?',(email(body.email),)).fetchone()
        # Equal-cost verification for absent accounts, avoiding a fast timing oracle.
        stored=user['password'] if user else DUMMY_PASSWORD_HASH
        if not password_ok(body.password,stored) or not user: raise HTTPException(401,'Email or password is incorrect')
        log(c,dict(user),None,'auth.login')
        return session(c,user['id'],response)
@app.get('/api/auth/me')
def me(user=Depends(get_user)): return user
@app.post('/api/auth/logout')
def logout(request: Request,response: Response,user=Depends(get_user)):
    with db(True) as c: c.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(request.cookies[COOKIE].encode()).hexdigest(),))
    response.delete_cookie(COOKIE,path='/');return {'ok':True}

@app.get('/api/events')
def list_events(user=Depends(get_user)):
    with db() as c:
        rows=c.execute("SELECT e.*, (SELECT COUNT(*) FROM registrations r WHERE r.event_id=e.id AND r.status='confirmed') AS confirmed,(SELECT COUNT(*) FROM registrations r WHERE r.event_id=e.id AND r.status='waitlisted') AS waitlisted,(SELECT status FROM registrations r WHERE r.event_id=e.id AND r.user_id=?) AS my_status FROM events e WHERE e.status!='draft' OR e.owner_id=? ORDER BY e.start",(user['id'],user['id'])).fetchall()
        return [dict(r) for r in rows]
@app.post('/api/events',status_code=201)
def create_event(body: EventInput,user=Depends(get_user)):
    if user['role']!='organizer': raise HTTPException(403,'Organizer role required')
    start,end=iso(body.start),iso(body.end)
    if end<=start or body.status not in ('draft','published','closed'): raise HTTPException(422,'Invalid event dates or status')
    with db(True) as c:
        i=uid();c.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?)',(i,body.title,body.description,body.venue,start,end,body.capacity,body.status,int(body.feedback_required),user['id'],now()));log(c,user,i,'event.create',body.title)
    return {'id':i}
@app.get('/api/events/{event_id}')
def event_detail(event_id: str,user=Depends(get_user)):
    with db() as c:
        e=event(c,event_id)
        if e['status']=='draft' and e['owner_id']!=user['id']: raise HTTPException(404,'Event not found')
        result=dict(e)
        result['agenda']=[dict(r) for r in c.execute('SELECT * FROM agenda WHERE event_id=? ORDER BY start',(event_id,))]
        result['announcements']=[dict(r) for r in c.execute('SELECT * FROM announcements WHERE event_id=? ORDER BY created DESC',(event_id,))]
        reg=c.execute('SELECT * FROM registrations WHERE event_id=? AND user_id=?',(event_id,user['id'])).fetchone()
        result['registration']=dict(reg) if reg else None
        result['checked_in']=bool(reg and c.execute('SELECT 1 FROM attendance WHERE registration_id=?',(reg['id'],)).fetchone())
        result['feedback_submitted']=bool(c.execute('SELECT 1 FROM feedback WHERE event_id=? AND user_id=?',(event_id,user['id'])).fetchone())
        result['certificate']=None
        cert=c.execute('SELECT id,revoked,created FROM certificates WHERE event_id=? AND user_id=?',(event_id,user['id'])).fetchone()
        if cert: result['certificate']=dict(cert)
        return result

@app.post('/api/events/{event_id}/register',status_code=201)
def register(event_id: str,body: RegistrationInput,user=Depends(get_user)):
    with db(True) as c:
        e=event(c,event_id)
        if e['status']!='published': raise HTTPException(409,'Registration is not open')
        if user['role']!='participant': raise HTTPException(403,'Use a participant account to register')
        prev=c.execute('SELECT * FROM registrations WHERE event_id=? AND user_id=?',(event_id,user['id'])).fetchone()
        if prev and prev['status']!='cancelled': raise HTTPException(409,'Already registered for this event')
        count=c.execute("SELECT COUNT(*) FROM registrations WHERE event_id=? AND status='confirmed'",(event_id,)).fetchone()[0]
        status='confirmed' if count<e['capacity'] else 'waitlisted'
        i=prev['id'] if prev else uid();ticket=secrets.token_urlsafe(32)
        if prev: c.execute('UPDATE registrations SET status=?,preferences=?,ticket=?,created=? WHERE id=?',(status,body.preferences,ticket,now(),i))
        else: c.execute('INSERT INTO registrations VALUES(?,?,?,?,?,?,?)',(i,event_id,user['id'],status,body.preferences,ticket,now()))
        log(c,user,event_id,'registration.create',status)
    return {'id':i,'status':status,'ticket':ticket}
@app.post('/api/events/{event_id}/cancel')
def cancel(event_id: str,user=Depends(get_user)):
    with db(True) as c:
        row=c.execute('SELECT * FROM registrations WHERE event_id=? AND user_id=?',(event_id,user['id'])).fetchone()
        if not row or row['status']=='cancelled': raise HTTPException(409,'No active registration')
        if c.execute('SELECT 1 FROM attendance WHERE registration_id=?',(row['id'],)).fetchone(): raise HTTPException(409,'Cannot cancel after check-in')
        c.execute("UPDATE registrations SET status='cancelled' WHERE id=?",(row['id'],))
        promoted=None
        if row['status']=='confirmed':
            next_row=c.execute("SELECT id FROM registrations WHERE event_id=? AND status='waitlisted' ORDER BY created,id LIMIT 1",(event_id,)).fetchone()
            if next_row:
                promoted=next_row['id'];c.execute("UPDATE registrations SET status='confirmed' WHERE id=?",(promoted,))
        log(c,user,event_id,'registration.cancel',f'promoted={promoted or "none"}')
    return {'ok':True,'promoted':bool(promoted)}
@app.get('/api/events/{event_id}/ticket.png')
def ticket_qr(event_id: str,user=Depends(get_user)):
    with db() as c:
        reg=c.execute("SELECT ticket FROM registrations WHERE event_id=? AND user_id=? AND status='confirmed'",(event_id,user['id'])).fetchone()
        if not reg: raise HTTPException(403,'Confirmed registration required for a ticket')
    b=io.BytesIO();qrcode.make('eventops:'+reg['ticket']).save(b,format='PNG');b.seek(0)
    return StreamingResponse(b,media_type='image/png')
@app.get('/api/events/{event_id}/registrations')
def registrations(event_id: str,user=Depends(get_user)):
    with db() as c:
        owner(c,event_id,user)
        return [dict(r) for r in c.execute('SELECT r.*,u.name,u.email,a.created AS checked_in FROM registrations r JOIN users u ON u.id=r.user_id LEFT JOIN attendance a ON a.registration_id=r.id WHERE r.event_id=? ORDER BY r.created,r.id',(event_id,))]
@app.post('/api/events/{event_id}/checkin')
def checkin(event_id: str,body: CheckinInput,user=Depends(get_user)):
    if body.method not in ('manual','qr'): raise HTTPException(422,'Invalid check-in method')
    with db(True) as c:
        owner(c,event_id,user)
        token=body.ticket.removeprefix('eventops:')
        r=c.execute("SELECT r.*,u.name FROM registrations r JOIN users u ON u.id=r.user_id WHERE r.event_id=? AND r.ticket=? AND r.status='confirmed'",(event_id,token)).fetchone()
        if not r: raise HTTPException(404,'No confirmed ticket found for this event')
        previous=c.execute('SELECT created FROM attendance WHERE registration_id=?',(r['id'],)).fetchone()
        if previous: return {'name':r['name'],'already_checked_in':True,'created':previous['created']}
        stamp=now();c.execute('INSERT INTO attendance VALUES(?,?,?,?,?)',(uid(),r['id'],user['id'],body.method,stamp));log(c,user,event_id,'attendance.checkin',r['id'])
        return {'name':r['name'],'already_checked_in':False,'created':stamp}

@app.post('/api/events/{event_id}/feedback',status_code=201)
def feedback(event_id: str,body: FeedbackInput,user=Depends(get_user)):
    with db(True) as c:
        member(c,event_id,user)
        if user['role']!='participant': raise HTTPException(403,'Participant feedback only')
        if not c.execute('SELECT 1 FROM attendance a JOIN registrations r ON r.id=a.registration_id WHERE r.event_id=? AND r.user_id=?',(event_id,user['id'])).fetchone(): raise HTTPException(409,'Check in before submitting feedback')
        try: c.execute('INSERT INTO feedback VALUES(?,?,?,?,?,?)',(uid(),event_id,user['id'],body.rating,body.comment,now()))
        except sqlite3.IntegrityError: raise HTTPException(409,'Feedback already submitted')
        log(c,user,event_id,'feedback.submit')
    return {'ok':True}
@app.get('/api/events/{event_id}/feedback')
def feedback_report(event_id: str,user=Depends(get_user)):
    with db() as c:
        owner(c,event_id,user)
        items=[dict(r) for r in c.execute('SELECT rating,comment,created FROM feedback WHERE event_id=? ORDER BY created DESC',(event_id,))]
        distribution={str(i):sum(x['rating']==i for x in items) for i in range(1,6)}
        return {'items':items,'count':len(items),'average':round(sum(x['rating'] for x in items)/len(items),2) if items else None,'distribution':distribution}

@app.get('/api/events/{event_id}/resources')
def resource_list(event_id: str,user=Depends(get_user)):
    with db() as c:
        member(c,event_id,user)
        return [dict(r) for r in c.execute('SELECT id,event_id,title,kind,url,mime,size,created FROM resources WHERE event_id=? ORDER BY created DESC',(event_id,))]
@app.post('/api/events/{event_id}/resources',status_code=201)
def resource_link(event_id: str,body: ResourceInput,user=Depends(get_user)):
    parsed=urlparse(body.url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password: raise HTTPException(422,'Resource links must be HTTPS URLs without embedded credentials')
    with db(True) as c:
        owner(c,event_id,user);i=uid();c.execute('INSERT INTO resources VALUES(?,?,?,?,?,?,?,?,?)',(i,event_id,body.title,'link',body.url,None,None,0,now()));log(c,user,event_id,'resource.create',body.title)
    return {'id':i}
@app.post('/api/events/{event_id}/resources/upload',status_code=201)
async def resource_upload(event_id: str,title: str=Form(...,min_length=2,max_length=150),file: UploadFile=File(...),user=Depends(get_user)):
    with db() as c: owner(c,event_id,user)
    content=await file.read(10*1024*1024+1)
    if len(content)>10*1024*1024: raise HTTPException(413,'Maximum file size is 10 MB')
    ext=Path(file.filename or '').suffix.lower();types={'.pdf':'application/pdf','.txt':'text/plain','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp'}
    mime=types.get(ext)
    if not mime: raise HTTPException(422,'Allowed files: PDF, TXT, PNG, JPG, WEBP')
    valid=(ext=='.pdf' and content.startswith(b'%PDF-')) or (ext=='.png' and content.startswith(b'\x89PNG\r\n\x1a\n')) or (ext in ('.jpg','.jpeg') and content.startswith(b'\xff\xd8\xff')) or (ext=='.webp' and content[:4]==b'RIFF' and content[8:12]==b'WEBP') or (ext=='.txt' and b'\x00' not in content)
    if not valid: raise HTTPException(422,'File content does not match the extension')
    i=uid();filename=i+ext;path=DATA/'uploads'/filename
    path.write_bytes(content)
    try:
        with db(True) as c:
            owner(c,event_id,user);c.execute('INSERT INTO resources VALUES(?,?,?,?,?,?,?,?,?)',(i,event_id,title,'file',None,filename,mime,len(content),now()));log(c,user,event_id,'resource.upload',i)
    except Exception: path.unlink(missing_ok=True);raise
    return {'id':i}
@app.get('/api/resources/{resource_id}/download')
def resource_download(resource_id: str,user=Depends(get_user)):
    with db() as c:
        r=c.execute('SELECT * FROM resources WHERE id=?',(resource_id,)).fetchone()
        if not r or r['kind']!='file': raise HTTPException(404,'File not found')
        member(c,r['event_id'],user)
    path=(DATA/'uploads'/r['path']).resolve()
    if path.parent!=DATA/'uploads' or not path.is_file(): raise HTTPException(404,'File not found')
    return FileResponse(path,media_type=r['mime'],filename='event-resource'+path.suffix,content_disposition_type='attachment')

@app.get('/api/events/{event_id}/team')
def team(event_id: str,user=Depends(get_user)):
    with db() as c:
        owner(c,event_id,user)
        return [dict(r) for r in c.execute("SELECT id,name,email FROM users WHERE id=? OR id IN (SELECT user_id FROM registrations WHERE event_id=? AND status='confirmed') ORDER BY name",(user['id'],event_id))]
@app.get('/api/events/{event_id}/tasks')
def task_list(event_id: str,user=Depends(get_user)):
    with db() as c:
        member(c,event_id,user)
        is_owner=event(c,event_id)['owner_id']==user['id']
        rows=c.execute('SELECT t.*,u.name AS assignee FROM tasks t LEFT JOIN users u ON u.id=t.assignee_id WHERE t.event_id=? ORDER BY t.due,t.created',(event_id,)).fetchall()
        result=[]
        for row in rows:
            if not is_owner and row['assignee_id']!=user['id']: continue
            item=dict(row);item['dependencies']=[dict(x) for x in c.execute('SELECT t.id,t.title,t.status FROM task_dependencies d JOIN tasks t ON t.id=d.depends_on WHERE d.task_id=?',(row['id'],))];result.append(item)
        return result
@app.post('/api/events/{event_id}/tasks',status_code=201)
def create_task(event_id: str,body: TaskInput,user=Depends(get_user)):
    due=iso(body.due)
    if body.priority not in ('low','normal','high'): raise HTTPException(422,'Invalid priority')
    with db(True) as c:
        owner(c,event_id,user)
        if body.assignee_id:
            u=c.execute('SELECT id FROM users WHERE id=?',(body.assignee_id,)).fetchone()
            r=c.execute("SELECT 1 FROM registrations WHERE event_id=? AND user_id=? AND status='confirmed'",(event_id,body.assignee_id)).fetchone()
            if not u or (body.assignee_id!=user['id'] and not r): raise HTTPException(422,'Assign tasks only to this event’s confirmed team')
        for dependency in body.dependencies:
            if not c.execute('SELECT 1 FROM tasks WHERE id=? AND event_id=?',(dependency,event_id)).fetchone(): raise HTTPException(422,'Dependencies must belong to this event')
        i=uid();c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?)',(i,event_id,body.title,body.description,body.assignee_id,due,body.priority,'todo',now()))
        for dependency in set(body.dependencies): c.execute('INSERT INTO task_dependencies VALUES(?,?)',(i,dependency))
        log(c,user,event_id,'task.create',i)
    return {'id':i}
@app.patch('/api/tasks/{task_id}')
def update_task(task_id: str,body: TaskStatus,user=Depends(get_user)):
    if body.status not in ('todo','doing','done'): raise HTTPException(422,'Invalid task status')
    with db(True) as c:
        t=c.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
        if not t: raise HTTPException(404,'Task not found')
        e=member(c,t['event_id'],user)
        if user['id'] not in (e['owner_id'],t['assignee_id']): raise HTTPException(403,'Only the assignee or event organizer can update this task')
        if body.status=='done' and c.execute("SELECT 1 FROM task_dependencies d JOIN tasks t ON t.id=d.depends_on WHERE d.task_id=? AND t.status!='done'",(task_id,)).fetchone(): raise HTTPException(409,'Complete dependency tasks first')
        if body.status!='done' and c.execute("SELECT 1 FROM task_dependencies d JOIN tasks t ON t.id=d.task_id WHERE d.depends_on=? AND t.status='done'",(task_id,)).fetchone(): raise HTTPException(409,'Reopen completed dependent tasks first')
        c.execute('UPDATE tasks SET status=? WHERE id=?',(body.status,task_id));log(c,user,t['event_id'],'task.status',body.status)
    return {'ok':True}
@app.post('/api/events/{event_id}/announcements',status_code=201)
def announce(event_id: str,body: AnnouncementInput,user=Depends(get_user)):
    with db(True) as c:
        owner(c,event_id,user);i=uid();c.execute('INSERT INTO announcements VALUES(?,?,?,?,?)',(i,event_id,body.title,body.body,now()));log(c,user,event_id,'announcement.create',body.title)
    return {'id':i}
@app.post('/api/events/{event_id}/agenda',status_code=201)
def add_agenda(event_id: str,body: AgendaInput,user=Depends(get_user)):
    start,end=iso(body.start),iso(body.end)
    with db(True) as c:
        e=owner(c,event_id,user)
        if not(e['start']<=start<end<=e['end']): raise HTTPException(422,'Session must fit inside the event schedule')
        i=uid();c.execute('INSERT INTO agenda VALUES(?,?,?,?,?,?)',(i,event_id,body.title,body.speaker,start,end));log(c,user,event_id,'agenda.create',body.title)
    return {'id':i}

@app.get('/api/events/{event_id}/analytics')
def analytics(event_id: str,user=Depends(get_user)):
    with db() as c:
        e=owner(c,event_id,user)
        confirmed=c.execute("SELECT COUNT(*) FROM registrations WHERE event_id=? AND status='confirmed'",(event_id,)).fetchone()[0]
        checked=c.execute('SELECT COUNT(*) FROM attendance a JOIN registrations r ON r.id=a.registration_id WHERE r.event_id=?',(event_id,)).fetchone()[0]
        return {'confirmed':confirmed,'waitlisted':c.execute("SELECT COUNT(*) FROM registrations WHERE event_id=? AND status='waitlisted'",(event_id,)).fetchone()[0],'capacity':e['capacity'],'checked_in':checked,'attendance_rate':round(100*checked/confirmed,1) if confirmed else 0,'feedback_count':c.execute('SELECT COUNT(*) FROM feedback WHERE event_id=?',(event_id,)).fetchone()[0],'tasks_total':c.execute('SELECT COUNT(*) FROM tasks WHERE event_id=?',(event_id,)).fetchone()[0],'tasks_done':c.execute("SELECT COUNT(*) FROM tasks WHERE event_id=? AND status='done'",(event_id,)).fetchone()[0],'certificates':c.execute('SELECT COUNT(*) FROM certificates WHERE event_id=? AND revoked=0',(event_id,)).fetchone()[0]}
@app.get('/api/events/{event_id}/audit')
def audit_list(event_id: str,user=Depends(get_user)):
    with db() as c:
        owner(c,event_id,user)
        return [dict(r) for r in c.execute('SELECT a.id,a.action,a.detail,a.created,u.name AS actor FROM audit a LEFT JOIN users u ON u.id=a.actor_id WHERE a.event_id=? ORDER BY a.id DESC LIMIT 200',(event_id,))]
@app.get('/api/events/{event_id}/export.csv')
def export_csv(event_id: str,user=Depends(get_user)):
    def cell(value):
        value=str(value or '')
        return "'"+value if value.lstrip().startswith(('=','+','-','@','\t','\r')) else value
    with db() as c:
        owner(c,event_id,user)
        rows=c.execute('SELECT u.name,u.email,r.status,r.preferences,a.created AS checked_in,f.rating FROM registrations r JOIN users u ON u.id=r.user_id LEFT JOIN attendance a ON a.registration_id=r.id LEFT JOIN feedback f ON f.user_id=r.user_id AND f.event_id=r.event_id WHERE r.event_id=? ORDER BY r.created',(event_id,)).fetchall()
    out=io.StringIO();writer=csv.writer(out);writer.writerow(['Name','Email','Registration','Preferences','Check-in (UTC)','Rating'])
    for r in rows: writer.writerow([cell(x) for x in r])
    return Response(out.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="event-attendance.csv"'})

def issue(c,event_id,user_id,user):
    e=owner(c,event_id,user)
    r=c.execute("SELECT r.id FROM registrations r JOIN attendance a ON a.registration_id=r.id WHERE r.event_id=? AND r.user_id=? AND r.status='confirmed'",(event_id,user_id)).fetchone()
    if not r: raise HTTPException(409,'Participant must have a confirmed registration and attendance')
    if e['feedback_required'] and not c.execute('SELECT 1 FROM feedback WHERE event_id=? AND user_id=?',(event_id,user_id)).fetchone(): raise HTTPException(409,'Participant must submit feedback first')
    existing=c.execute('SELECT * FROM certificates WHERE event_id=? AND user_id=?',(event_id,user_id)).fetchone()
    if existing:
        if existing['revoked']: raise HTTPException(409,'Certificate was revoked; review the audit trail')
        return existing['id']
    i=uid();c.execute('INSERT INTO certificates VALUES(?,?,?,?,?,?)',(i,event_id,user_id,secrets.token_urlsafe(32),0,now()));log(c,user,event_id,'certificate.issue',i)
    return i
@app.post('/api/events/{event_id}/certificates/{user_id}',status_code=201)
def issue_certificate(event_id: str,user_id: str,user=Depends(get_user)):
    with db(True) as c: i=issue(c,event_id,user_id,user)
    return {'id':i}
@app.post('/api/events/{event_id}/certificates/batch/issue')
def batch_certificates(event_id: str,user=Depends(get_user)):
    issued=[];skipped=[]
    with db(True) as c:
        owner(c,event_id,user)
        candidates=c.execute("SELECT user_id FROM registrations WHERE event_id=? AND status='confirmed'",(event_id,)).fetchall()
        for r in candidates:
            try: issued.append(issue(c,event_id,r['user_id'],user))
            except HTTPException as e:
                if e.status_code!=409: raise
                skipped.append({'user_id':r['user_id'],'reason':e.detail})
    return {'issued':issued,'skipped':skipped}
@app.get('/api/events/{event_id}/certificates')
def certificates(event_id: str,user=Depends(get_user)):
    with db() as c:
        owner(c,event_id,user)
        return [dict(r) for r in c.execute('SELECT c.id,c.created,c.revoked,u.name,u.email FROM certificates c JOIN users u ON u.id=c.user_id WHERE c.event_id=? ORDER BY c.created DESC',(event_id,))]
@app.post('/api/certificates/{certificate_id}/revoke')
def revoke(certificate_id: str,user=Depends(get_user)):
    with db(True) as c:
        cert=c.execute('SELECT * FROM certificates WHERE id=?',(certificate_id,)).fetchone()
        if not cert: raise HTTPException(404,'Certificate not found')
        owner(c,cert['event_id'],user);c.execute('UPDATE certificates SET revoked=1 WHERE id=?',(certificate_id,));log(c,user,cert['event_id'],'certificate.revoke',certificate_id)
    return {'ok':True}
@app.get('/api/certificates/{certificate_id}/download')
def certificate_pdf(certificate_id: str,user=Depends(get_user)):
    with db() as c:
        r=c.execute('SELECT c.*,u.name,e.title,e.owner_id FROM certificates c JOIN users u ON u.id=c.user_id JOIN events e ON e.id=c.event_id WHERE c.id=?',(certificate_id,)).fetchone()
        if not r: raise HTTPException(404,'Certificate not found')
        if user['id'] not in (r['user_id'],r['owner_id']): raise HTTPException(403,'Certificate access denied')
        if r['revoked']: raise HTTPException(410,'Certificate revoked')
    b=io.BytesIO();p=canvas.Canvas(b,pagesize=(842,595));p.setTitle('EventOps participation certificate')
    p.setFillColorRGB(.97,.98,1);p.rect(0,0,842,595,fill=1,stroke=0)
    p.setStrokeColorRGB(.18,.3,.65);p.setLineWidth(2);p.rect(28,28,786,539,fill=0,stroke=1)
    p.setFillColorRGB(.12,.18,.30);p.setFont('Helvetica-Bold',14);p.drawString(60,519,'EVENTOPS / VERIFIED PARTICIPATION')
    p.setFont('Times-Roman',42);p.drawCentredString(421,405,'Certificate of Participation')
    p.setFont('Helvetica',15);p.drawCentredString(421,350,'This certificate is presented to')
    # Embed a Unicode font if installed; fallback is documented for container portability.
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    fontpath=Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    if fontpath.exists() and 'EventOpsUnicode' not in pdfmetrics.getRegisteredFontNames(): pdfmetrics.registerFont(TTFont('EventOpsUnicode',str(fontpath)))
    font='EventOpsUnicode' if fontpath.exists() else 'Helvetica'
    p.setFont(font,min(30,600/max(len(r['name']),1)*1.6));p.drawCentredString(421,296,r['name'])
    p.setFont('Helvetica',14);p.drawCentredString(421,250,'for attending')
    p.setFont(font,min(20,600/max(len(r['title']),1)*1.6));p.drawCentredString(421,218,r['title'])
    p.setFont('Helvetica',10);p.drawString(60,95,'Issued: '+r['created'][:10]);p.drawString(60,76,'Certificate: '+r['id'])
    image=qrcode.make(BASE_URL+'/?verify='+r['verify_token']);q=io.BytesIO();image.save(q,format='PNG');q.seek(0);p.drawImage(ImageReader(q),685,65,95,95)
    p.drawString(60,57,'Scan the QR code to verify validity. Revoked certificates are marked invalid.');p.showPage();p.save();b.seek(0)
    return StreamingResponse(b,media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="certificate-{certificate_id[:10]}.pdf"'})
@app.get('/api/verify/{token}')
def verify(token: str,request: Request):
    throttle('verify:'+request.client.host,60,60)
    with db() as c:
        r=c.execute('SELECT c.id,c.revoked,c.created,u.name,e.title FROM certificates c JOIN users u ON u.id=c.user_id JOIN events e ON e.id=c.event_id WHERE c.verify_token=?',(token,)).fetchone()
        if not r: raise HTTPException(404,'Certificate not found')
        return {'valid':not bool(r['revoked']),'certificate_id':r['id'],'recipient':r['name'],'event':r['title'],'issued':r['created'][:10]}

# No broad data directory mount: uploads and PDFs are served only after authorization.
app.mount('/',StaticFiles(directory=ROOT/'web',html=True),name='web')
