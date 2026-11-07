"""INVEREX Bank Recon cloud demo: synthetic data ONLY, ephemeral storage, NOT production."""
import os,sys,json,sqlite3,hashlib,secrets,hmac,time,zipfile,mimetypes,datetime,io,html,shutil,threading,webbrowser
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs
from http.cookies import SimpleCookie
from calendar import monthrange
CLOUD_DEMO=os.environ.get('RECON_CLOUD_DEMO')=='1'
ROOT=Path(__file__).resolve().parent;DATA=ROOT/'data';BACKUPS=DATA/'archive';DB=DATA/'recon.sqlite3';LOGO=ROOT/'static'/'inverex_logo.png';MAX_UPLOAD=15_000_000
LOGIN_ATTEMPTS={}
SEED=json.loads((DATA/'seed.json').read_text(encoding='utf8'))
def db():
 c=sqlite3.connect(DB,timeout=15);c.row_factory=sqlite3.Row;c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA foreign_keys=ON');return c
def init():
 DATA.mkdir(exist_ok=True);BACKUPS.mkdir(exist_ok=True)
 with db() as c:
  c.executescript('''CREATE TABLE IF NOT EXISTS users(email TEXT PRIMARY KEY,display TEXT NOT NULL, role TEXT NOT NULL, salt TEXT NOT NULL, hash TEXT NOT NULL,active INTEGER DEFAULT 1);
  CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,email TEXT NOT NULL,created TEXT NOT NULL,last_seen TEXT NOT NULL,expires INTEGER NOT NULL,revoked INTEGER DEFAULT 0);
  CREATE TABLE IF NOT EXISTS banks(id INTEGER PRIMARY KEY,bu TEXT,bank TEXT,month TEXT,closing_date TEXT,erp REAL,bank_close REAL,adjusted_erp REAL,adjusted_bank REAL,origin TEXT,UNIQUE(bu,bank,month));
  CREATE TABLE IF NOT EXISTS entries(id TEXT PRIMARY KEY,bu TEXT,bank TEXT,month TEXT,source_sheet TEXT,source_row INTEGER,employee TEXT,category TEXT,txn_date TEXT,particulars TEXT,reference TEXT,erp_amount REAL,bank_amount REAL,flags TEXT,status TEXT DEFAULT 'Pending',posted_date TEXT,remarks TEXT DEFAULT '',updated_by TEXT,updated_at TEXT);
  CREATE TABLE IF NOT EXISTS historical(id INTEGER PRIMARY KEY,bu TEXT,bank TEXT,month TEXT,description TEXT,amount REAL,source_row INTEGER);
  CREATE TABLE IF NOT EXISTS uploads(id INTEGER PRIMARY KEY,bu TEXT,bank TEXT,month TEXT,kind TEXT,filename TEXT,stored TEXT,sha256 TEXT,bytes INTEGER,added_by TEXT,added_at TEXT,UNIQUE(bu,bank,month,kind,sha256));
  CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,when_utc TEXT,actor TEXT,action TEXT,target TEXT,details TEXT);''')
  if c.execute('SELECT COUNT(*) FROM banks').fetchone()[0]==0:
   for x in SEED['banks']:c.execute('INSERT INTO banks(bu,bank,month,closing_date,erp,bank_close,adjusted_erp,adjusted_bank,origin) VALUES(?,?,?,?,?,?,?,?,?)',(x['bu'],x['bank'],x['month'],x['closing_date'],x['erp'],x['bank_close'],x['adjusted_erp'],x['adjusted_bank'],x['source']))
  if c.execute('SELECT COUNT(*) FROM entries').fetchone()[0]==0:
   for x in SEED['entries']:
    c.execute('INSERT INTO entries(id,bu,bank,month,source_sheet,source_row,employee,category,txn_date,particulars,reference,erp_amount,bank_amount,flags) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(x['id'],x['bu'],x['bank'],x['month'],x['source_sheet'],x['source_row'],x['employee'],x['category'],x['date'],x['particulars'],x['reference'],x['erp_amount'],x['bank_amount'],x['flags']))
  if c.execute('SELECT COUNT(*) FROM historical').fetchone()[0]==0:
   for x in SEED['historical']:c.execute('INSERT INTO historical(bu,bank,month,description,amount,source_row) VALUES(?,?,?,?,?,?)',(x['bu'],x['bank'],x['month'],x['description'],x['amount'],x['source_row']))
  if c.execute('SELECT COUNT(*) FROM users').fetchone()[0]==0:
   pwd=os.environ.get('RECON_ADMIN_PASSWORD') or (None if CLOUD_DEMO else secrets.token_urlsafe(15))
   if not pwd:raise RuntimeError('RECON_ADMIN_PASSWORD must be set for cloud demo')
   add_user(c,'admin@local.invalid','Local Admin (QA)', 'admin',pwd)
   if not CLOUD_DEMO:print('\n=== FIRST RUN - LOCAL QA ONLY ===\nUSER: admin@local.invalid\nPASSWORD: '+pwd+'\nSAVE THIS PASSWORD. IT IS DISPLAYED ONLY AT FIRST RUN.\n',flush=True)
def seed_demo_csv():
 if not CLOUD_DEMO:return
 now=datetime.datetime.now(datetime.timezone.utc).isoformat()
 examples={
  'Bank Statement':b'Date,Reference,Signed Amount\n2026-10-15,DEMO01,1000.00\n2026-10-16,DEMO02,-350.00\n2026-10-18,DEMO03,2500.00\n',
  'Ledger':b'Date,Reference,Signed Amount\n2026-10-15,DEMO01,1000.00\n2026-10-17,DEMO02,-350.00\n2026-10-18,DEMO04,5000.00\n'
 }
 for kind,raw in examples.items():
  filename='DEMO_'+kind.replace(' ','_')+'.csv';sha=hashlib.sha256(raw).hexdigest()
  directory=BACKUPS/'APT'/'2026-10'/'Meezan'/kind.replace(' ','_');directory.mkdir(parents=True,exist_ok=True)
  rel=(directory/(sha[:16]+'_'+filename)).relative_to(BACKUPS)
  with db() as c:
   if c.execute('SELECT 1 FROM uploads WHERE bu=? AND bank=? AND month=? AND kind=? AND sha256=?',('APT','Meezan','2026-10',kind,sha)).fetchone():continue
   (BACKUPS/rel).write_bytes(raw)
   c.execute('INSERT INTO uploads(bu,bank,month,kind,filename,stored,sha256,bytes,added_by,added_at) VALUES(?,?,?,?,?,?,?,?,?,?)',('APT','Meezan','2026-10',kind,filename,str(rel),sha,len(raw),'synthetic-demo',now))

def ph(p,s):return hashlib.pbkdf2_hmac('sha256',p.encode(),bytes.fromhex(s),280000).hex()
def add_user(c,e,name,role,password):
 s=secrets.token_hex(16);c.execute('INSERT INTO users(email,display,role,salt,hash) VALUES(?,?,?,?,?)',(e,name,role,s,ph(password,s)))
def audit(c,actor,action,target,details=''):
 c.execute('INSERT INTO audit(when_utc,actor,action,target,details) VALUES(?,?,?,?,?)',(datetime.datetime.now(datetime.timezone.utc).isoformat(),actor,action,target,details))
def asdict(rows):return [dict(x) for x in rows]
def age(date,month):
 try:
  if not date:return None
  dt=datetime.datetime.strptime(date,'%d-%b-%Y').date()
  year,m=map(int,month.split('-'));end=datetime.date(year,m,monthrange(year,m)[1]);return max(0,(end-dt).days)
 except:return None
def bucket(d):return 'Date Missing' if d is None else '0–30' if d<=30 else '31–60' if d<=60 else '61–90' if d<=90 else '91–180' if d<=180 else '180+'
def category(x):
 t=x.upper()
 if 'CHEQUE ISSUED' in t or 'NOT YET DEBITED BY BANK' in t:return 'ERP cheque not debited'
 if 'DEBITED BY BANK' in t:return 'Bank debit not in ERP'
 if 'CREDITED BY BANK' in t:return 'Bank credit not in ERP'
 return 'Other / review'
def amount(r):return abs((r['erp_amount'] if r['erp_amount'] is not None else r['bank_amount']) or 0)
def make_xlsx(rows,headers):
 # minimal Office Open XML (.xlsx), no third-party spreadsheet dependency
 from xml.sax.saxutils import escape
 def col(n):
  s='';n+=1
  while n:n,k=divmod(n-1,26);s=chr(65+k)+s
  return s
 out=io.BytesIO()
 with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
  z.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
  z.writestr('_rels/.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
  z.writestr('xl/workbook.xml','<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Admin Working" sheetId="1" r:id="rId1"/></sheets></workbook>')
  z.writestr('xl/_rels/workbook.xml.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
  s=['<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><sheetData>']
  for ri,line in enumerate([headers]+rows,1):
   s.append('<row r="%d">'%ri)
   for ci,v in enumerate(line):
    if v is None:continue
    a=f'{col(ci)}{ri}'
    if isinstance(v,(int,float)) and not isinstance(v,bool):s.append(f'<c r="{a}"><v>{v}</v></c>')
    else:s.append(f'<c r="{a}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>')
   s.append('</row>')
  s.append('</sheetData></worksheet>');z.writestr('xl/worksheets/sheet1.xml',''.join(s))
 return out.getvalue()
def pdf_summary(banks,historical,month,bu):
 from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,Image
 from reportlab.lib.styles import getSampleStyleSheet
 from reportlab.lib import colors
 from reportlab.lib.units import inch
 b=io.BytesIO();doc=SimpleDocTemplate(b,pagesize=(842,595),topMargin=35,bottomMargin=28,leftMargin=38,rightMargin=38)
 styles=getSampleStyleSheet();story=[]
 if LOGO.exists():
  try:
   from PIL import Image as PILImage
   im=PILImage.open(LOGO);w,h=im.size;story.append(Image(str(LOGO),width=100,height=100*h/w))
  except:pass
 story += [Paragraph('<b>INVEREX GROUP OF COMPANIES</b>',styles['Heading2']),Paragraph(f'Monthly Bank Reconciliation Summary | {html.escape(bu)} | {html.escape(month)}',styles['Heading3']),Paragraph('Source: frozen original reconciliation data. Employee updates excluded.',styles['Normal']),Spacer(1,12)]
 headers=['Business Unit','Bank','Closing Date','ERP Closing','Bank Closing','Raw Difference','Adjusted Difference'];data=[headers]
 for r in banks:
  if not ((r['erp'] or 0) or (r['bank_close'] or 0)):continue
  data.append([r['bu'],r['bank'],r['closing_date'],f"{r['erp']:,.2f}" if r['erp'] is not None else '—',f"{r['bank_close']:,.2f}" if r['bank_close'] is not None else '—',f"{r['bank_close']-r['erp']:,.2f}" if r['erp'] is not None and r['bank_close'] is not None else '—',f"{r['adjusted_erp']-r['adjusted_bank']:,.2f}" if r['adjusted_erp'] is not None and r['adjusted_bank'] is not None else '—'])
 if len(data)==1:data.append(['No source data','','','','','',''])
 t=Table(data,repeatRows=1,colWidths=[78,103,90,111,111,111,110]);t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#14695F')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#E9F5EF')]),('FONTSIZE',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),8),('ALIGN',(3,1),(-1,-1),'RIGHT')]));story.append(t)
 if historical:
  story.extend([Spacer(1,15),Paragraph('<b>Historical Closing Bridge Alerts (not included in raw closing difference)</b>',styles['Heading3'])])
  for a in historical:story.append(Paragraph(f"{html.escape(a['bu'])} / {html.escape(a['bank'])}: {html.escape(a['description'])} — Rs. {a['amount']:,.2f}",styles['Normal']))
 story.extend([Spacer(1,15),Paragraph('Prepared from uploaded source-mapped reports; not an independently certified bank/ERP reconciliation.',styles['Italic'])]);doc.build(story);return b.getvalue()

def read_standard_csv(raw):
 import csv,decimal
 try:txt=raw.decode('utf-8-sig')
 except:txt=raw.decode('cp1252')
 parser=csv.DictReader(io.StringIO(txt));fields={str(f).strip().lower():f for f in (parser.fieldnames or [])}
 refcol=next((fields[k] for k in ('reference','ref','transaction reference','cheque #') if k in fields),None)
 datecol=next((fields[k] for k in ('date','transaction date','bank date') if k in fields),None)
 amtcol=next((fields[k] for k in ('signed amount','amount') if k in fields),None)
 debitcol=next((fields[k] for k in ('debit','dr') if k in fields),None)
 creditcol=next((fields[k] for k in ('credit','cr') if k in fields),None)
 if not refcol or not (amtcol or (debitcol and creditcol)):raise ValueError('CSV must have Reference + signed Amount or Debit and Credit columns')
 def dec(v):
  v=(v or '').strip().replace(',','').replace('(','-').replace(')','')
  return decimal.Decimal(v or '0')
 result=[]
 for n,r in enumerate(parser,2):
  if not any((v or '').strip() for v in r.values()):continue
  a=dec(r[amtcol]) if amtcol else dec(r[creditcol])-dec(r[debitcol])
  result.append({'line':n,'reference':(r.get(refcol) or '').strip(),'date':(r.get(datecol) or '').strip() if datecol else '', 'signed_amount':str(a)})
 return result

def match_csv(bank_raw,ledger_raw):
 # Safety: only exact normalized references + signed amount, no date-only/amount-only auto matching
 from collections import defaultdict
 bank=read_standard_csv(bank_raw);ledger=read_standard_csv(ledger_raw)
 def key(r):return (''.join(c for c in r['reference'].upper() if c.isalnum()),r['signed_amount'])
 lidx=defaultdict(list)
 for r in ledger:
  if key(r)[0]:lidx[key(r)].append(r)
 matched=[];bank_unmatched=[];used=set()
 for b in bank:
  k=key(b);candidates=[x for x in lidx[k] if x['line'] not in used] if k[0] else []
  if len(candidates)==1:
   x=candidates[0];used.add(x['line']);matched.append({'bank':b,'erp':x,'method':'Exact reference + signed amount'})
  else:bank_unmatched.append(b)
 erp_unmatched=[x for x in ledger if x['line'] not in used]
 return {'bank_count':len(bank),'erp_count':len(ledger),'match_count':len(matched),'matched':matched,'bank_unmatched':bank_unmatched,'erp_unmatched':erp_unmatched,'method':'Exact reference + signed amount only; statement-vs-ERP signs must follow compatible convention; dates not required','certification':'Preliminary candidates only; human verification required'}

class Handler(BaseHTTPRequestHandler):
 def log_message(self,format,*args):pass
 def send(self,data,status=200,ctype='application/json',headers={}):
  if isinstance(data,(dict,list)):data=json.dumps(data,default=str).encode()
  if isinstance(data,str):data=data.encode()
  self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY');
  if CLOUD_DEMO:self.send_header('Strict-Transport-Security','max-age=31536000; includeSubDomains')
  self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; connect-src 'self'")
  for k,v in headers.items():self.send_header(k,v)
  self.end_headers();self.wfile.write(data)
 def cookie(self):
  try:c=SimpleCookie(self.headers.get('Cookie',''));return c['recon'].value if 'recon' in c else ''
  except:return ''
 def identity(self):
  token=self.cookie()
  if not token:return None
  with db() as c:
   row=c.execute('SELECT s.email,u.role,u.display,s.expires,s.revoked FROM sessions s JOIN users u ON u.email=s.email WHERE s.token_hash=? AND u.active=1',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
   if not row or row['expires']<time.time() or row['revoked']:return None
   c.execute('UPDATE sessions SET last_seen=? WHERE token_hash=?',(datetime.datetime.now(datetime.timezone.utc).isoformat(),hashlib.sha256(token.encode()).hexdigest()))
   return dict(row)
 def payload(self):
  length=int(self.headers.get('Content-Length','0'))
  if length>MAX_UPLOAD:raise ValueError('Payload over 15MB limit')
  return self.rfile.read(length)
 def jsonbody(self):return json.loads(self.payload().decode())
 def require(self,roles=()):
  user=self.identity()
  if not user:self.send({'error':'Login required'},401);return None
  if roles and user['role'] not in roles:self.send({'error':'Not authorized'},403);return None
  return user
 def do_GET(self):
  url=urlparse(self.path);p=url.path;q=parse_qs(url.query)
  if p=='/' or p=='/index.html':return self.send((ROOT/'static'/'index.html').read_bytes(),ctype='text/html; charset=utf-8')
  if p=='/app.js':return self.send((ROOT/'static'/'app.js').read_bytes(),ctype='application/javascript')
  if p=='/style.css':return self.send((ROOT/'static'/'style.css').read_bytes(),ctype='text/css')
  if p=='/logo.png':return self.send(LOGO.read_bytes(),ctype='image/png')
  if p=='/health':return self.send({'ok':True,'mode':'synthetic_demo' if CLOUD_DEMO else 'local'})
  if p=='/api/me':return self.send({'user':self.identity(),'local_qa_only':not CLOUD_DEMO,'synthetic_demo':CLOUD_DEMO,'otp_enabled':False})
  user=self.require();
  if not user:return
  if p=='/api/data':
   with db() as c:
    banks=asdict(c.execute('SELECT * FROM banks ORDER BY bu,bank').fetchall());entries=asdict(c.execute('SELECT * FROM entries ORDER BY bu,bank,source_row').fetchall());historical=asdict(c.execute('SELECT * FROM historical').fetchall());uploads=asdict(c.execute('SELECT id,bu,bank,month,kind,filename,sha256,bytes,added_at FROM uploads').fetchall())
    aud=asdict(c.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 40').fetchall()) if user['role']=='admin' else []
    sessions=asdict(c.execute('SELECT u.display,s.email,s.created,s.last_seen,s.revoked,s.expires,substr(s.token_hash,1,10) AS session_id FROM sessions s JOIN users u ON u.email=s.email WHERE s.expires>? ORDER BY s.created DESC',(int(time.time()),)).fetchall()) if user['role']=='admin' else []
   if user['role']=='employee':entries=[e for e in entries if e['employee'].casefold()==user['display'].casefold()]
   return self.send({'banks':banks,'entries':entries,'historical':historical,'uploads':uploads,'audit':aud,'sessions':sessions,'user':user})
  if p=='/api/auto-match':
   bu=q.get('bu',[''])[0];bank=q.get('bank',[''])[0];month=q.get('month',[''])[0]
   with db() as c:
    x=asdict(c.execute('SELECT * FROM uploads WHERE bu=? AND bank=? AND month=? AND filename LIKE \u0027%.csv\u0027 ORDER BY id DESC',(bu,bank,month)).fetchall())
   l=next((r for r in x if r['kind']=='Ledger'),None);b=next((r for r in x if r['kind']=='Bank Statement'),None)
   if not l or not b:return self.send({'error':'Upload standardized CSV Bank Statement and Ledger for same BU/bank/month first'},400)
   try:return self.send(match_csv((BACKUPS/b['stored']).read_bytes(),(BACKUPS/l['stored']).read_bytes()))
   except Exception as e:return self.send({'error':str(e)},400)
  if p=='/api/export/admin.xlsx':
   if user['role']!='admin':return self.send({'error':'Admin only'},403)
   with db() as c:r=asdict(c.execute('SELECT * FROM entries ORDER BY bu,bank,source_row').fetchall())
   h=['BU','Bank','Month','Source Row','Employee','Category','Original Date','Particulars','Reference','ERP Debit/Credit','Bank Debit/Credit','ERP Status','ERP Posted Date','Employee Remarks','Validation Flags']
   keys=['bu','bank','month','source_row','employee','category','txn_date','particulars','reference','erp_amount','bank_amount','status','posted_date','remarks','flags']
   return self.send(make_xlsx([[x[k] for k in keys] for x in r],h),ctype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename="INVEREX_Admin_Full_Working.xlsx"'})
  if p=='/api/export/summary.pdf':
   bu=q.get('bu',['ALL'])[0];month=q.get('month',['2026-10'])[0]
   with db() as c:
    banks=asdict(c.execute('SELECT * FROM banks WHERE (?="ALL" OR bu=?) AND month=?',(bu,bu,month)).fetchall());historical=asdict(c.execute('SELECT * FROM historical WHERE (?="ALL" OR bu=?) AND month=?',(bu,bu,month)).fetchall())
   return self.send(pdf_summary(banks,historical,month,bu),ctype='application/pdf',headers={'Content-Disposition':'attachment; filename="INVEREX_Monthly_Summary.pdf"'})
  if p.startswith('/api/download/'):
   try:fid=int(p.rsplit('/',1)[-1])
   except:return self.send({'error':'Invalid file id'},400)
   with db() as c:r=c.execute('SELECT * FROM uploads WHERE id=?',(fid,)).fetchone()
   if not r:return self.send({'error':'Not found'},404)
   fp=BACKUPS/str(r['stored'])
   if not fp.is_file() or BACKUPS.resolve() not in fp.resolve().parents:return self.send({'error':'Missing file'},404)
   return self.send(fp.read_bytes(),ctype='application/octet-stream',headers={'Content-Disposition':f"attachment; filename*=UTF-8''{__import__('urllib.parse',fromlist=['quote']).quote(r['filename'])}"})
  return self.send({'error':'Unknown endpoint'},404)
 def do_POST(self):
  url=urlparse(self.path);p=url.path
  try:
   if CLOUD_DEMO:
    origin=self.headers.get('Origin','')
    if origin:
     from urllib.parse import urlsplit
     if urlsplit(origin).netloc!=self.headers.get('Host',''):return self.send({'error':'Cross-origin request forbidden'},403)
   if p=='/api/login':
    body=self.jsonbody();email=str(body.get('email','')).strip().lower();passwd=body.get('password','')
    if CLOUD_DEMO:
     attempts=[t for t in LOGIN_ATTEMPTS.get(email,[]) if time.time()-t<900]
     if len(attempts)>=5:return self.send({'error':'Too many login attempts. Try later.'},429)
     LOGIN_ATTEMPTS[email]=attempts
    with db() as c:r=c.execute('SELECT * FROM users WHERE email=? AND active=1',(email,)).fetchone()
    if not r or not hmac.compare_digest(ph(passwd,r['salt']),r['hash']):
     if CLOUD_DEMO:LOGIN_ATTEMPTS[email].append(time.time())
     return self.send({'error':'Invalid login'},401)
    if CLOUD_DEMO:LOGIN_ATTEMPTS.pop(email,None)
    token=secrets.token_urlsafe(40);now=datetime.datetime.now(datetime.timezone.utc).isoformat()
    with db() as c:
     c.execute('INSERT INTO sessions VALUES(?,?,?,?,?,0)',(hashlib.sha256(token.encode()).hexdigest(),email,now,now,int(time.time())+3600));audit(c,email,'LOGIN','session')
    return self.send({'ok':True},headers={'Set-Cookie':f'recon={token}; HttpOnly; SameSite=Strict; {"Secure; " if CLOUD_DEMO else ""}Path=/; Max-Age=3600'})
   user=self.require()
   if not user:return
   if p=='/api/logout':
    with db() as c:c.execute('UPDATE sessions SET revoked=1 WHERE token_hash=?',(hashlib.sha256(self.cookie().encode()).hexdigest(),));audit(c,user['email'],'LOGOUT','self')
    return self.send({'ok':True},headers={'Set-Cookie':('recon=; HttpOnly; SameSite=Strict; '+('Secure; ' if CLOUD_DEMO else '')+'Max-Age=0; Path=/')})
   if p=='/api/entry':
    if user['role'] not in ('admin','employee'):return self.send({'error':'Read only'},403)
    b=self.jsonbody();id=str(b.get('id',''));status=b.get('status');date=b.get('posted_date') or None;remarks=str(b.get('remarks',''))[:1500]
    if status not in ('Pending','Entry Posted'):return self.send({'error':'Choose Pending or Entry Posted'},400)
    if status=='Entry Posted':
     try:datetime.date.fromisoformat(date)
     except:return self.send({'error':'Entry Posted requires a valid ERP posting date'},400)
    elif date:return self.send({'error':'Pending entries cannot have ERP posted date'},400)
    with db() as c:
     row=c.execute('SELECT employee FROM entries WHERE id=?',(id,)).fetchone()
     if not row:return self.send({'error':'Entry not found'},404)
     if user['role']=='employee' and row['employee'].casefold()!=user['display'].casefold():return self.send({'error':'Not assigned to this employee'},403)
     c.execute('UPDATE entries SET status=?,posted_date=?,remarks=?,updated_by=?,updated_at=? WHERE id=?',(status,date,remarks,user['email'],datetime.datetime.now(datetime.timezone.utc).isoformat(),id));audit(c,user['email'],'ENTRY_UPDATE',id,status+' '+(date or ''))
    return self.send({'ok':True})
   if p=='/api/revoke':
    if user['role']!='admin':return self.send({'error':'Admin only'},403)
    b=self.jsonbody();sid=str(b.get('session_id',''))
    with db() as c:
     rows=c.execute('SELECT token_hash,email FROM sessions WHERE substr(token_hash,1,10)=?',(sid,)).fetchall()
     for r in rows:
      if r['email']==user['email']:continue
      c.execute('UPDATE sessions SET revoked=1 WHERE token_hash=?',(r['token_hash'],));audit(c,user['email'],'REMOTE_LOGOUT',r['email'])
    return self.send({'ok':True})
   if p=='/api/upload':
    if CLOUD_DEMO:return self.send({'error':'Public synthetic demo: user uploads disabled. No confidential company records allowed.'},403)
    if user['role']!='admin':return self.send({'error':'Admin only'},403)
    # JSON with base64 encoded file, explicit bank/month/type; originals immutable
    import base64,re
    b=self.jsonbody();bu=str(b.get('bu',''));bank=str(b.get('bank',''));month=str(b.get('month',''));kind=str(b.get('kind',''))
    if bu not in ('APT','IPS','INVEREX PVT','INVEREX ELECTRONIC','ISE PVT') or not re.fullmatch(r'20\d\d-(0[1-9]|1[012])',month) or kind not in ('Ledger','Bank Statement','Frozen Recon','Supporting Image') or not bank or not __import__('re').fullmatch(r'[A-Za-z0-9 _-]{1,70}',bank):return self.send({'error':'Invalid BU, bank, month or kind'},400)
    name=Path(str(b.get('filename','')).replace('\\','/')).name
    if not name or len(name)>150 or not name.lower().endswith(('.xlsx','.csv','.pdf','.jpg','.jpeg','.png','.zip')):return self.send({'error':'Unsupported file'},400)
    raw=base64.b64decode(b.get('base64',''),validate=True)
    if len(raw)>10_000_000:return self.send({'error':'File too large'},400)
    ext=Path(name).suffix.lower()
    if ext=='.zip':
     with zipfile.ZipFile(io.BytesIO(raw)) as z:
      if len(z.infolist())>200 or sum(i.file_size for i in z.infolist())>100_000_000:return self.send({'error':'ZIP archive exceeds safe limits'},400)
      for f in z.infolist():
       if '..' in Path(f.filename.replace('\\','/')).parts or f.filename.startswith(('/', '\\')):return self.send({'error':'Unsafe archive path'},400)
    if ext in ('.png','.jpg','.jpeg'):
     from PIL import Image as PILImage
     from reportlab.pdfgen import canvas
     try:
      im=PILImage.open(io.BytesIO(raw));im.verify();im=PILImage.open(io.BytesIO(raw));im.thumbnail((2300,3200));im=im.convert('RGB');buf=io.BytesIO();im.save(buf,format='PDF');raw=buf.getvalue();name=Path(name).stem+'.pdf'
     except:return self.send({'error':'Invalid image'},400)
    if ext=='.pdf' and not raw.startswith(b'%PDF-'):return self.send({'error':'Invalid PDF signature'},400)
    if ext=='.xlsx' and not zipfile.is_zipfile(io.BytesIO(raw)):return self.send({'error':'Invalid Excel workbook'},400)
    hashv=hashlib.sha256(raw).hexdigest();dir=BACKUPS/bu/month/bank.replace('/','_')/kind.replace(' ','_');dir.mkdir(parents=True,exist_ok=True)
    dst=dir/(hashv[:16]+'_'+name);stored=dst.relative_to(BACKUPS)
    with db() as c:
     if c.execute('SELECT 1 FROM uploads WHERE bu=? AND bank=? AND month=? AND kind=? AND sha256=?',(bu,bank,month,kind,hashv)).fetchone():return self.send({'error':'Duplicate file already archived'},409)
     dst.write_bytes(raw)
     c.execute('INSERT INTO uploads(bu,bank,month,kind,filename,stored,sha256,bytes,added_by,added_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(bu,bank,month,kind,name,str(stored),hashv,len(raw),user['email'],datetime.datetime.now(datetime.timezone.utc).isoformat()));audit(c,user['email'],'FILE_ARCHIVED',str(stored),hashv)
    return self.send({'ok':True,'sha256':hashv,'note':'Archived. No automated parsing/matching is triggered yet.'})
   return self.send({'error':'Unknown endpoint'},404)
  except (ValueError,KeyError,zipfile.BadZipFile) as e:return self.send({'error':str(e)},400)
  except Exception as e:return self.send({'error':'Server error; inspect server logs'},500)
if __name__=='__main__':
 if CLOUD_DEMO and not os.environ.get('RECON_ADMIN_PASSWORD'):raise SystemExit('Missing RECON_ADMIN_PASSWORD secret')
 init();seed_demo_csv();port=int(os.environ.get('PORT',os.environ.get('RECON_PORT','8765')));host='0.0.0.0' if CLOUD_DEMO else '127.0.0.1'
 print('SYNTHETIC DEMO ONLY' if CLOUD_DEMO else 'LOCAL QA ONLY',flush=True)
 ThreadingHTTPServer((host,port),Handler).serve_forever()
