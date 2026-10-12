"""Local administration. Demo credentials are intentionally public: never seed production."""
import argparse, getpass, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.main import db, initialize, password_hash, email, uid, now, DATA, SECURE

DEMO_PASSWORD='DemoEventOps!2026'
def create_user(c,name,address,role,password):
    i=uid();c.execute('INSERT INTO users VALUES(?,?,?,?,?,?)',(i,name,email(address),password_hash(password),role,now()));return i

def seed():
    if SECURE: raise SystemExit('Demo seeding is not allowed in secure production mode.')
    initialize()
    with db(True) as c:
        if c.execute('SELECT COUNT(*) FROM users').fetchone()[0]: raise SystemExit('Database is not empty. Demo seed will not overwrite any users or event records.')
        c.execute("INSERT INTO settings VALUES('demo','1')")
        organizer=create_user(c,'Alex Morgan','organizer@eventops.test','organizer',DEMO_PASSWORD)
        guest=create_user(c,'Jordan Lee','participant@eventops.test','participant',DEMO_PASSWORD)
        sam=create_user(c,'Sam Rivera','sam@eventops.test','participant',DEMO_PASSWORD)
        riley=create_user(c,'Riley Chen','riley@eventops.test','participant',DEMO_PASSWORD)
        import secrets
        event_id=uid(); start=(datetime.now(timezone.utc)+timedelta(days=14)).replace(hour=9,minute=0,second=0,microsecond=0);end=start+timedelta(hours=8)
        stamp=now()
        c.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?)',(event_id,'Build Together Summit','A hands-on day of product thinking, collaborative workshops, and ideas worth sharing.','Innovation Hall · Bengaluru',start.isoformat(),end.isoformat(),80,'published',1,organizer,stamp))
        event2=uid();c.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?)',(event2,'Design & Develop Workshop','A focused workshop on accessible interfaces and practical full-stack engineering.','Studio 04 · Online',(start+timedelta(days=7)).isoformat(),(end+timedelta(days=7)).isoformat(),2,'published',0,organizer,stamp))
        registrations={}
        for person,pref in [(guest,'Vegetarian meal'),(sam,''),(riley,'Step-free access')]:
            rid=uid();registrations[person]=rid;c.execute('INSERT INTO registrations VALUES(?,?,?,?,?,?,?)',(rid,event_id,person,'confirmed',pref,secrets.token_urlsafe(32),stamp))
        c.execute('INSERT INTO attendance VALUES(?,?,?,?,?)',(uid(),registrations[sam],organizer,'manual',stamp))
        c.execute('INSERT INTO feedback VALUES(?,?,?,?,?,?)',(uid(),event_id,sam,5,'The collaborative session was thoughtfully organized. More time for the final Q&A would make it even better.',stamp))
        c.execute('INSERT INTO attendance VALUES(?,?,?,?,?)',(uid(),registrations[riley],organizer,'manual',stamp))
        c.execute('INSERT INTO feedback VALUES(?,?,?,?,?,?)',(uid(),event_id,riley,4,'Clear directions and a welcoming team. I would love the slides ahead of the next workshop.',stamp))
        agenda=[('Welcome & opening','Alex Morgan',0,1),('From idea to prototype','Workshop team',1,3),('Collaboration lab','Community facilitators',4,6),('Showcase & closing','All participants',6,8)]
        for title,speaker,a,b in agenda:c.execute('INSERT INTO agenda VALUES(?,?,?,?,?,?)',(uid(),event_id,title,speaker,(start+timedelta(hours=a)).isoformat(),(start+timedelta(hours=b)).isoformat()))
        c.execute('INSERT INTO announcements VALUES(?,?,?,?,?)',(uid(),event_id,'Your day, made easy','Doors open 30 minutes before the opening session. Bring your personal QR ticket and a laptop for the collaboration lab.',stamp))
        c.execute('INSERT INTO announcements VALUES(?,?,?,?,?)',(uid(),event_id,'A shared library for everyone','Workshop resources are available in your Resources tab. Your feedback helps shape our next gathering.',stamp))
        c.execute('INSERT INTO resources VALUES(?,?,?,?,?,?,?,?,?)',(uid(),event_id,'Accessible interface reference','link','https://www.w3.org/WAI/fundamentals/accessibility-intro/',None,None,0,stamp))
        c.execute('INSERT INTO resources VALUES(?,?,?,?,?,?,?,?,?)',(uid(),event_id,'Python documentation','link','https://docs.python.org/3/',None,None,0,stamp))
        tasks=[]
        for title,desc,person,status,priority in [('Confirm venue layout','Review seating, signage, and step-free access.',organizer,'done','high'),('Prepare workshop materials','Finalize the starter kits and session notes.',sam,'doing','high'),('Welcome desk checklist','Print name badges and review check-in flow.',guest,'todo','normal'),('Publish participant guide','Share the arrival guide and final schedule.',riley,'todo','normal')]:
            tid=uid();tasks.append(tid);c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?)',(tid,event_id,title,desc,person,(start-timedelta(days=2)).isoformat(),priority,status,stamp))
        c.execute('INSERT INTO task_dependencies VALUES(?,?)',(tasks[2],tasks[0]))
        c.execute('INSERT INTO certificates VALUES(?,?,?,?,?,?)',(uid(),event_id,sam,secrets.token_urlsafe(32),0,stamp))
        c.execute('INSERT INTO audit(actor_id,event_id,action,detail,created) VALUES(?,?,?,?,?)',(organizer,event_id,'demo.seed','Fictional demo event and participants',stamp))
    print('Demo workspace initialized. All names, attendance, and metrics are fictional.')
    print('Organizer: organizer@eventops.test')
    print('Participant: participant@eventops.test')
    print('Demo password for both: '+DEMO_PASSWORD)
    print('Use a separate, unseeded database for deployment.')

def main():
    parser=argparse.ArgumentParser(description='EventOps local administration')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('seed-demo')
    create=sub.add_parser('create-organizer');create.add_argument('--name',required=True);create.add_argument('--email',required=True)
    sub.add_parser('init-db')
    args=parser.parse_args()
    if args.command=='seed-demo':return seed()
    initialize()
    if args.command=='init-db':print('Database ready at '+str(DATA));return
    password=getpass.getpass('Organizer password (at least 12 characters): ')
    if len(password)<12 or len(password)>128:raise SystemExit('Password must be 12–128 characters.')
    if password!=getpass.getpass('Confirm password: '):raise SystemExit('Passwords do not match.')
    with db(True) as c:
        if c.execute('SELECT 1 FROM users WHERE email=?',(email(args.email),)).fetchone():raise SystemExit('Account already exists. No changes made.')
        create_user(c,args.name,args.email,'organizer',password)
    print('Organizer created. Password is not stored in plaintext.')
if __name__=='__main__':main()
