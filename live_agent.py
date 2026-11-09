"""Durable browser bridge. Extension owns UI; this process owns inference and deduplication."""
import json,hashlib,re,time,threading,sqlite3,uuid,secrets,os,random
from datetime import datetime,timezone
LOCK=threading.RLock()
ROOT=None
SERVICE=None
HEARTBEATS={}

def utc(): return datetime.now(timezone.utc).isoformat()
def delivered_text_matches(expected,actual):
    if expected==actual:return True
    # LovePlanet renders emoji as images; innerText omits these images.
    plain=lambda s:re.sub(r'\s+',' ',re.sub('[\U0001F300-\U0001FAFF\uFE0F\u200D]','',s)).strip()
    a,b=plain(expected),plain(actual)
    return len(re.findall(r'\w',a))>=8 and a==b
def is_invitation(text,account,config):
    username=config['accounts'][account]['telegram'].rsplit('/',1)[-1]
    return bool(re.search(r'(?<![A-Za-z0-9_])'+re.escape(username)+r'(?![A-Za-z0-9_])',text,re.I))
def atomic(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(obj,ensure_ascii=False,indent=2));os.chmod(temp,0o600);temp.replace(path)
def db():
    c=sqlite3.connect(ROOT/'live.sqlite',timeout=10);c.row_factory=sqlite3.Row;return c

def init(service):
    global ROOT,SERVICE,KEY
    SERVICE=service;ROOT=service.DATA
    key=ROOT/'bridge.key'
    if not key.exists(): key.write_text(secrets.token_urlsafe(32));os.chmod(key,0o600)
    KEY=key.read_text().strip()
    with db() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS live_turns (
        id TEXT PRIMARY KEY,account TEXT NOT NULL,contact TEXT NOT NULL,incoming TEXT NOT NULL,
        status TEXT NOT NULL,due REAL NOT NULL,created REAL NOT NULL,reply TEXT,engine TEXT,error TEXT,
        claimed REAL, site_id TEXT, UNIQUE(account,contact,incoming));
        CREATE TABLE IF NOT EXISTS live_contacts(account TEXT,contact TEXT,stopped INTEGER DEFAULT 0,declined INTEGER DEFAULT 0, PRIMARY KEY(account,contact));''')
        c.execute('CREATE TABLE IF NOT EXISTS live_accounts(account TEXT PRIMARY KEY,next_send REAL DEFAULT 0)')
        contact_columns={r[1] for r in c.execute('PRAGMA table_info(live_contacts)')}
        if 'next_send' not in contact_columns:c.execute('ALTER TABLE live_contacts ADD COLUMN next_send REAL DEFAULT 0')
        for account in SERVICE.CONFIG['accounts']:c.execute('INSERT OR IGNORE INTO live_accounts(account) VALUES(?)',(account,))
        columns={r[1] for r in c.execute('PRAGMA table_info(live_turns)')}
        if 'attempts' not in columns:c.execute('ALTER TABLE live_turns ADD COLUMN attempts INTEGER DEFAULT 0')
        c.execute("UPDATE live_turns SET status='queued' WHERE status='generating'")
        # A crash after a click is ambiguous: never blindly retry a possibly delivered message.
        c.execute("UPDATE live_turns SET status='uncertain' WHERE status='sending'")
    os.chmod(ROOT/'live.sqlite',0o600)

def validate(doc):
    if doc.get('account') not in SERVICE.CONFIG['accounts']: raise ValueError('unknown_account')
    if not re.fullmatch('[a-zA-Z0-9_-]{1,100}',str(doc.get('contact',''))): raise ValueError('invalid_contact')
    ms=doc.get('messages',[])
    if not isinstance(ms,list) or len(ms)>500: raise ValueError('invalid_history')
    for m in ms:
        if m.get('role') not in ('user','assistant') or not re.fullmatch(r'\d{1,30}',str(m.get('id',''))) or not isinstance(m.get('text'),str) or len(m['text'])>10000: raise ValueError('invalid_message')
    return doc['account'],doc['contact'],ms

def history_path(account,contact): return ROOT/'dialogs'/(account+'--'+contact+'.json')
def ledger():
    p=ROOT/'live-events.json'
    return json.loads(p.read_text()) if p.exists() else {'events':[]}

def record(turn,message,doc):
    data=ledger();eid=hashlib.sha256((turn['account']+'|'+message['id']).encode()).hexdigest()[:24]
    if not any(e.get('eventId')==eid or (e.get('siteMessageId')==message['id'] and e['account']==turn['account']) for e in data['events']):
        actual_model=turn['engine'].split(':',1)[1] if (turn['engine'] or '').startswith('ollama:') else SERVICE.MODEL
        data['events'].append(dict(eventId=eid,siteMessageId=message['id'],account=turn['account'],contact=turn['contact'],name=doc['name'],reply=message['text'],at=utc(),kind='reply_sent',model=actual_model,engine=turn['engine'],confirmed=True,confirmation='extension_readback',reviewed=False,autonomous=True))
        data['events'][-1]['telegramInvitation']=is_invitation(message['text'],turn['account'],SERVICE.CONFIG)
        atomic(ROOT/'live-events.json',data)
    with db() as c:c.execute("UPDATE live_turns SET status='sent',site_id=? WHERE id=?",(message['id'],turn['id']))

def snapshot(doc,client):
    account,contact,ms=validate(doc)
    with LOCK:
        now=time.time();old=HEARTBEATS.get(account,{})
        if old.get('client')!=client and now-old.get('at',0)<30: return {'status':'other_tab_active'}
        HEARTBEATS[account]={**old,'client':client,'at':now,'contact':contact,'status':'connected'}
        path=history_path(account,contact)
        # Merge paginated history. Keep old content rather than infer deletion from an incomplete page.
        prior=json.loads(path.read_text()) if path.exists() else {'messages':[]}
        merged={m['id']:m for m in prior['messages']}
        merged.update({m['id']:m for m in ms})
        saved={'account':account,'contact':contact,'name':str(doc.get('name',contact))[:140],'updatedAt':utc(),'messages':sorted(merged.values(),key=lambda m:int(m['id']))}
        atomic(path,saved)
        if not ms:return {'status':'empty'}
        last=ms[-1]
        with db() as c:
            uncertain=c.execute("SELECT * FROM live_turns WHERE account=? AND contact=? AND status IN ('sending','uncertain')",(account,contact)).fetchall()
        for t in uncertain:
            match=next((m for m in ms if m['role']=='assistant' and int(m['id'])>int(t['incoming']) and delivered_text_matches(t['reply'],m['text']) and not re.search('Отправляется|Ошибка',m.get('date',''))),None)
            if match:record(t,match,saved)
        with db() as c:
            c.execute('INSERT OR IGNORE INTO live_contacts(account,contact) VALUES(?,?)',(account,contact))
            state=c.execute('SELECT * FROM live_contacts WHERE account=? AND contact=?',(account,contact)).fetchone()
            c.execute("UPDATE live_turns SET status='superseded' WHERE account=? AND contact=? AND incoming!=? AND status IN ('queued','generating','ready')",(account,contact,last['id']))
            if last['role']!='user':return {'status':'waiting_for_contact'}
            if state['stopped']:
                goodbye=c.execute("SELECT * FROM live_turns WHERE account=? AND contact=? AND incoming=? AND status='ready'",(account,contact,last['id'])).fetchone()
                return dict(goodbye) if goodbye else {'status':'waiting_for_contact'}
            if c.execute("SELECT 1 FROM live_turns WHERE account=? AND contact=? AND status IN ('sending','uncertain')",(account,contact)).fetchone():return {'status':'delivery_uncertain'}
            tid=hashlib.sha256((account+'|'+contact+'|'+last['id']).encode()).hexdigest()[:24]
            c.execute("INSERT OR IGNORE INTO live_turns(id,account,contact,incoming,status,due,created) VALUES(?,?,?,?,?,?,?)",(tid,account,contact,last['id'],'queued',now+random.uniform(SERVICE.CONFIG['delay_min_seconds'],SERVICE.CONFIG['delay_max_seconds']),now))
            turn=dict(c.execute('SELECT * FROM live_turns WHERE id=?',(tid,)).fetchone())
            return turn

def process(account):
    with LOCK,db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute("SELECT * FROM live_turns WHERE account=? AND status='queued' AND due<=? ORDER BY due LIMIT 1",(account,time.time())).fetchone()
        if not row:return False
        t=dict(row);c.execute("UPDATE live_turns SET status='generating',attempts=attempts+1,error=NULL WHERE id=?",(t['id'],))
        status=dict(c.execute('SELECT * FROM live_contacts WHERE account=? AND contact=?',(account,t['contact'])).fetchone())
    try:
        doc=json.loads(history_path(account,t['contact']).read_text())
        status['invited']=any('t.me/' in m['text'] or SERVICE.CONFIG['accounts'][account]['telegram'].split('/')[-1] in m['text'] for m in doc['messages'] if m['role']=='assistant')
        history=[{'role':m['role'],'content':m['text']} for m in doc['messages'][-60:]]
        if t.get('error') and hasattr(SERVICE,'generate_repaired'):
            reply,updates,engine=SERVICE.generate_repaired(status,history,t['error'])
        else:reply,updates,engine=SERVICE.generate(status,history)
        with LOCK,db() as c:
            c.execute("UPDATE live_turns SET status='ready',reply=?,engine=? WHERE id=? AND status='generating'",(reply,engine,t['id']))
            # Stop/decline takes effect only on a still-current generation.
            if c.execute('SELECT status FROM live_turns WHERE id=?',(t['id'],)).fetchone()[0]=='ready':
                for k,v in updates.items():
                    if k in ('stopped','declined'):c.execute('UPDATE live_contacts SET '+k+'=? WHERE account=? AND contact=?',(v,account,t['contact']))
    except Exception as e:
        code=str(e) if isinstance(e,ValueError) else type(e).__name__
        permanent=code in ('openrouter_invalid_key','openrouter_key_missing','openrouter_quota_exhausted')
        retry=not permanent and t.get('attempts',0)<2
        pause=2 if code.endswith('_guard') or code=='invalid_generation' else 30*(t.get('attempts',0)+1)
        with db() as c:c.execute("UPDATE live_turns SET status=?,error=?,due=? WHERE id=? AND status='generating'",('queued' if retry else 'error',code[:80],time.time()+pause,t['id']))
    return True

def claim(tid,client,last):
    with LOCK,db() as c:
        c.execute('BEGIN IMMEDIATE');t=c.execute('SELECT * FROM live_turns WHERE id=?',(tid,)).fetchone()
        if not t or t['status']!='ready' or t['incoming']!=last:return {'status':'stale'}
        h=HEARTBEATS.get(t['account'],{})
        if h.get('client')!=client or time.time()-h.get('at',0)>30:return {'status':'lease_expired'}
        minimum=SERVICE.CONFIG.get('minimum_extension_version')
        if minimum and h.get('scan',{}).get('version')!=minimum:return {'status':'extension_update_required'}
        if h.get('scan',{}).get('siteStatus')=='offline':return {'status':'site_unavailable'}
        now=time.time()
        contact_next=c.execute('SELECT next_send FROM live_contacts WHERE account=? AND contact=?',(t['account'],t['contact'])).fetchone()[0]
        if now<max(t['due'],contact_next) or now<c.execute('SELECT next_send FROM live_accounts WHERE account=?',(t['account'],)).fetchone()[0]:return {'status':'waiting_delay'}
        if hasattr(SERVICE,'check_reply_policy'):
            doc=json.loads(history_path(t['account'],t['contact']).read_text())
            history=[{'role':m['role'],'content':m['text']} for m in doc['messages']]
            try:SERVICE.check_reply_policy(t['reply'],history)
            except ValueError as e:
                c.execute("UPDATE live_turns SET status='queued',reply=NULL,engine=NULL,attempts=0,error=?,due=? WHERE id=?",(str(e),now+2,tid))
                return {'status':'policy_requeued'}
        gap=random.uniform(SERVICE.CONFIG.get('send_gap_min_seconds',45),SERVICE.CONFIG.get('send_gap_max_seconds',90))
        c.execute('UPDATE live_accounts SET next_send=? WHERE account=?',(now+gap,t['account']))
        c.execute('UPDATE live_contacts SET next_send=? WHERE account=? AND contact=?',(now+SERVICE.CONFIG.get('chat_send_gap_seconds',60),t['account'],t['contact']))
        c.execute("UPDATE live_turns SET status='sending',claimed=? WHERE id=?",(time.time(),tid))
        return {'status':'send','reply':t['reply'],'id':tid,'contact':t['contact'],'incoming':t['incoming']}

def poll(account,client,scan=None):
    if account not in SERVICE.CONFIG['accounts']:raise ValueError('unknown_account')
    with LOCK:
        now=time.time();h=HEARTBEATS.get(account,{})
        if h.get('client')!=client and now-h.get('at',0)<30:return {'status':'other_tab_active'}
        scan=scan if isinstance(scan,dict) else {}
        progress={k:max(0,min(100000,v)) for k,v in scan.items() if k in ('loaded','read') and isinstance(v,int)}
        progress['version']=str(scan.get('version','0.3.x'))[:20]
        progress['siteStatus']='offline' if scan.get('siteStatus')=='offline' else 'online' if scan.get('siteStatus')=='online' else 'unknown'
        HEARTBEATS[account]={**h,'client':client,'at':now,'status':'connected','scan':progress}
    with db() as c:
        c.execute("UPDATE live_turns SET status='uncertain' WHERE status='sending' AND claimed<?",(now-60,))
        pending=[dict(r) for r in c.execute("SELECT id,contact,status,due,incoming FROM live_turns WHERE account=? AND status IN ('ready','queued','generating','sending','uncertain') ORDER BY CASE status WHEN 'uncertain' THEN 0 WHEN 'ready' THEN 1 ELSE 2 END,created",(account,))]
        contact_delays={r['contact']:r['next_send'] for r in c.execute('SELECT contact,next_send FROM live_contacts WHERE account=?',(account,))}
        for turn in pending:turn['due']=max(turn['due'],contact_delays.get(turn['contact'],0))
        next_send=c.execute('SELECT next_send FROM live_accounts WHERE account=?',(account,)).fetchone()[0]
    return {'status':'connected','turns':pending,'serverTime':now,'nextSendAt':next_send}

def status():
    with LOCK,db() as c:
        counts=[dict(r) for r in c.execute('SELECT account,status,COUNT(*) count FROM live_turns GROUP BY account,status')]
        return {'model':SERVICE.MODEL,'status':'connected' if any(time.time()-v['at']<30 for v in HEARTBEATS.values()) else 'offline','accounts':{a:{'status':'connected' if time.time()-HEARTBEATS.get(a,{}).get('at',0)<30 else 'offline','scan':HEARTBEATS.get(a,{}).get('scan',{}),'lastSeenAt':HEARTBEATS.get(a,{}).get('at'),'nextSendAt':c.execute('SELECT next_send FROM live_accounts WHERE account=?',(a,)).fetchone()[0]} for a in SERVICE.CONFIG['accounts']},'counts':counts}

def request(body):
    action=body.get('action');client=str(body.get('client',''))
    if not re.fullmatch('[a-zA-Z0-9:._-]{1,100}',client):raise ValueError('invalid_client')
    if action=='snapshot':return snapshot(body['dialog'],client)
    if action=='poll':return poll(body['account'],client,body.get('scan'))
    if action=='claim':return claim(body['id'],client,body['incoming'])
    if action=='delivery_error':
        with LOCK,db() as c:
            turn=c.execute('SELECT * FROM live_turns WHERE id=?',(body.get('id'),)).fetchone()
            if not turn or HEARTBEATS.get(turn['account'],{}).get('client')!=client:return {'status':'lease_expired'}
            c.execute("UPDATE live_turns SET status='uncertain',error='site_connection_lost' WHERE id=? AND status='sending'",(turn['id'],))
        return {'status':'delivery_uncertain'}
    if action=='status':return status()
    raise ValueError('invalid_action')

def worker(account):
    while not SERVICE.STOP.is_set():
        try: process(account)
        except Exception: pass
        SERVICE.STOP.wait(1)

def start(service):
    init(service)
    for account in SERVICE.CONFIG['accounts']:
        for _ in range(max(1,min(3,int(SERVICE.CONFIG.get('generation_workers_per_account',2))))):
            threading.Thread(target=worker,args=(account,),daemon=True).start()
