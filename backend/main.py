"""Order-to-Audit prototype. Stock is derived from immutable source-linked movements."""
from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from contextlib import contextmanager
import sqlite3, json, io, csv, os, hashlib, hmac, secrets, re

HERE=Path(__file__).resolve().parent
DB=Path(os.getenv('ORDER_AUDIT_DB', HERE/'order_audit.db'))
app=FastAPI(title='Order-to-Audit | Annam Foods', version='1.0.0')
ROLES={'admin','salesman','production','auditor','owner'}
USERS={'admin':('admin','Factory Admin'),'sales-a':('salesman','Salesman A'),'sales-b':('salesman','Salesman B'),'production':('production','Production Supervisor'),'auditor':('auditor','Auditor'),'owner':('owner','Owner')}
DEMO_PASSWORD='AnnamDemo2026!'

@contextmanager
def conn():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON')
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
def init():
    with conn() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, name TEXT, sku TEXT UNIQUE, pack_g INTEGER, price_paise INTEGER, gst_rate INTEGER, hsn TEXT, opening_qty INTEGER DEFAULT 0, expected_batch_qty INTEGER DEFAULT 200);
        CREATE TABLE IF NOT EXISTS customers(id INTEGER PRIMARY KEY, name TEXT, state TEXT, gstin TEXT, salesperson TEXT);
        CREATE TABLE IF NOT EXISTS materials(id INTEGER PRIMARY KEY, name TEXT, unit TEXT, rate_paise INTEGER, opening_qty REAL, category TEXT);
        CREATE TABLE IF NOT EXISTS bom(product_id INTEGER, material_id INTEGER, qty REAL, unit TEXT, PRIMARY KEY(product_id,material_id));
        CREATE TABLE IF NOT EXISTS movements(id INTEGER PRIMARY KEY, item_type TEXT, item_id INTEGER, qty REAL, source_type TEXT, source_id TEXT, note TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS production(id INTEGER PRIMARY KEY, product_id INTEGER, expected_qty INTEGER, actual_qty INTEGER, issued_json TEXT, damaged_pouches INTEGER, cartons_used INTEGER, labour_paise INTEGER, utilities_paise INTEGER, material_cost_paise INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, customer_id INTEGER, salesperson TEXT, status TEXT, lines_json TEXT, subtotal_paise INTEGER, gst_paise INTEGER, total_paise INTEGER, invoice_no TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, invoiced_at TEXT);
        CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY, order_id INTEGER, amount_paise INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, user TEXT, action TEXT, document TEXT, detail TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS users(user_id TEXT PRIMARY KEY, role TEXT NOT NULL, display TEXT NOT NULL, password_salt TEXT NOT NULL, password_hash TEXT NOT NULL, is_demo INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')
        legacy_users=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo_users'").fetchone()
        if legacy_users:
            c.execute('''INSERT OR IGNORE INTO users(user_id,role,display,password_salt,password_hash,is_demo)
                SELECT user_id,role,display,password_salt,password_hash,1 FROM demo_users''')
        product_columns={row['name'] for row in c.execute('PRAGMA table_info(products)')}
        if 'expected_batch_qty' not in product_columns: c.execute('ALTER TABLE products ADD COLUMN expected_batch_qty INTEGER DEFAULT 200')
        order_columns={row['name'] for row in c.execute('PRAGMA table_info(orders)')}
        if 'invoiced_at' not in order_columns: c.execute('ALTER TABLE orders ADD COLUMN invoiced_at TEXT')
        if c.execute('SELECT COUNT(*) FROM products').fetchone()[0]==0: seed(c)
        for user,(user_role,display) in USERS.items():
            if c.execute('SELECT 1 FROM users WHERE user_id=?',(user,)).fetchone(): continue
            salt=secrets.token_bytes(16)
            password_hash=hashlib.pbkdf2_hmac('sha256',DEMO_PASSWORD.encode(),salt,210000).hex()
            c.execute('INSERT OR IGNORE INTO users(user_id,role,display,password_salt,password_hash,is_demo) VALUES(?,?,?,?,?,1)',(user,user_role,display,salt.hex(),password_hash))
def seed(c):
    c.execute("INSERT INTO products(id,name,sku,pack_g,price_paise,gst_rate,hsn,opening_qty,expected_batch_qty) VALUES(1,'Murukku 200 g','MUR-200',200,5000,5,'210690',50,200)")
    c.executemany('INSERT INTO customers VALUES(?,?,?,?,?)',[(1,'Retailer A','Tamil Nadu','33AABCU9603R1ZM','sales-a'),(2,'Distributor B','Karnataka','29AABCU9603R1ZK','sales-b')])
    mats=[('Flour','kg',4200,100,'raw'),('Cooking oil','L',14000,30,'raw'),('Salt and spice mix','kg',20000,5,'raw'),('200 g pouch','piece',250,500,'packaging'),('Carton (20 packets)','piece',1500,30,'packaging')]
    c.executemany('INSERT INTO materials(name,unit,rate_paise,opening_qty,category) VALUES(?,?,?,?,?)',mats)
    c.executemany('INSERT INTO bom VALUES(?,?,?,?)',[(1,1,40,'kg'),(1,2,10,'L'),(1,3,1.2,'kg'),(1,4,200,'piece'),(1,5,10,'piece')])
    c.execute("INSERT INTO audit(user,action,document,detail) VALUES('system','seed','benchmark','Section 5 benchmark master data loaded')")
init()

def role(x):
    u=(x or '').strip().lower()
    with conn() as c: account=c.execute('SELECT role FROM users WHERE user_id=?',(u,)).fetchone()
    if not account: raise HTTPException(401,'Unknown user')
    return u,account['role']
def require(x,allowed):
    u,r=role(x)
    if r not in allowed: raise HTTPException(403,'Role not allowed')
    return u,r
def current_user(request:Request):
    token=request.cookies.get('oa_session')
    if not token: raise HTTPException(401,'Please sign in')
    now=datetime.now(timezone.utc).isoformat(timespec='seconds')
    token_hash=hashlib.sha256(token.encode()).hexdigest()
    with conn() as c:
        session=c.execute('SELECT user_id FROM sessions WHERE token_hash=? AND expires_at>?',(token_hash,now)).fetchone()
    if not session: raise HTTPException(401,'Session expired. Please sign in again')
    return session['user_id']
def rupees_to_paise(amount:Decimal)->int:
    return int((amount*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def weighted_average_rate_paise(old_qty,old_rate_paise,new_qty:Decimal,new_rate_paise:int)->int:
    old_quantity=Decimal(str(old_qty))
    total_quantity=old_quantity+new_qty
    if total_quantity<=0: return new_rate_paise
    weighted=(old_quantity*Decimal(old_rate_paise)+new_qty*Decimal(new_rate_paise))/total_quantity
    return int(weighted.quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def quantity_text(quantity)->str:
    value=Decimal(str(quantity))
    return format(value.quantize(Decimal('1')) if value==value.to_integral_value() else value.normalize(),'f')
def material_stock(c,mid):
    opening=c.execute('SELECT opening_qty FROM materials WHERE id=?',(mid,)).fetchone()[0]
    return opening+(c.execute('SELECT COALESCE(SUM(qty),0) FROM movements WHERE item_type="material" AND item_id=?',(mid,)).fetchone()[0])
def fg_stock(c,pid):
    opening=c.execute('SELECT opening_qty FROM products WHERE id=?',(pid,)).fetchone()[0]
    return opening+c.execute('SELECT COALESCE(SUM(qty),0) FROM movements WHERE item_type="product" AND item_id=?',(pid,)).fetchone()[0]
def log(c,u,action,doc,detail): c.execute('INSERT INTO audit(user,action,document,detail) VALUES(?,?,?,?)',(u,action,str(doc),json.dumps(detail)))
class Login(BaseModel): username:str; password:str
class Registration(BaseModel): username:str; display_name:str; password:str
class ManagedUser(BaseModel): username:str; display_name:str; password:str; role:str
class CustomerAssignment(BaseModel): customer_ids:list[int]
class Purchase(BaseModel): qty:Decimal; unit_price_rupees:Decimal=Decimal('45.00')
class Run(BaseModel): flour:Decimal=Decimal('40'); oil:Decimal=Decimal('10.5'); spice:Decimal=Decimal('1.2'); actual_output:int=188; damaged_pouches:int=6; cartons_used:int=9; labour_rupees:Decimal=Decimal('1200.00'); utilities_rupees:Decimal=Decimal('600.00')
class OrderIn(BaseModel): customer_id:int; quantity:int
class Decision(BaseModel): approved:bool=True; quantity:int|None=None; unit_price_paise:int|None=None
class Payment(BaseModel): amount_rupees:Decimal

USER_ID_PATTERN=re.compile(r'^[a-z0-9][a-z0-9._-]{2,29}$')
ASSIGNABLE_ROLES={'salesman','production','auditor'}
def validate_account(username,display_name,password):
    user=username.strip().lower()
    display=display_name.strip()
    if not USER_ID_PATTERN.fullmatch(user): raise HTTPException(400,'Username must be 3–30 characters using letters, numbers, dots, underscores, or hyphens')
    if not display or len(display)>80: raise HTTPException(400,'Display name must be between 1 and 80 characters')
    if len(password)<12 or len(password)>128 or not password.strip(): raise HTTPException(400,'Password must be 12–128 characters and cannot be blank')
    return user,display
def password_credentials(password):
    salt=secrets.token_bytes(16)
    password_hash=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,210000).hex()
    return salt.hex(),password_hash

@app.post('/api/login')
def login(v:Login):
    with conn() as c:
        account=c.execute('SELECT * FROM users WHERE user_id=?',(v.username.strip().lower(),)).fetchone()
        if not account: raise HTTPException(401,'Invalid username or password')
        salt=bytes.fromhex(account['password_salt'])
        candidate=hashlib.pbkdf2_hmac('sha256',v.password.encode(),salt,210000).hex()
        if not hmac.compare_digest(candidate,account['password_hash']): raise HTTPException(401,'Invalid username or password')
        token=secrets.token_urlsafe(32)
        expires=datetime.now(timezone.utc)+timedelta(hours=12)
        c.execute('INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),account['user_id'],expires.isoformat(timespec='seconds')))
    response=JSONResponse({'user':account['user_id'],'role':account['role'],'display':account['display'],'is_demo':bool(account['is_demo'])})
    response.set_cookie('oa_session',token,httponly=True,samesite='lax',secure=os.getenv('ORDER_AUDIT_COOKIE_SECURE','0')=='1',max_age=43200)
    return response

@app.post('/api/register',status_code=201)
def register(v:Registration):
    username,display=validate_account(v.username,v.display_name,v.password)
    salt,password_hash=password_credentials(v.password)
    with conn() as c:
        try:
            c.execute('INSERT INTO users(user_id,role,display,password_salt,password_hash,is_demo) VALUES(?,?,?,?,?,0)',(username,'salesman',display,salt,password_hash))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409,'That username is already in use') from exc
    return {'user':username,'role':'salesman','display':display,'message':'Account created. Sign in; an admin must assign customer accounts before you can place orders.'}

@app.get('/api/users')
def list_users(x_user:str=Depends(current_user)):
    require(x_user,{'admin','owner'})
    with conn() as c:
        accounts=[dict(row) for row in c.execute('SELECT user_id,role,display,is_demo,created_at FROM users ORDER BY is_demo DESC,user_id')]
        customers=[dict(row) for row in c.execute('SELECT id,name,salesperson FROM customers ORDER BY name')]
    return {'users':accounts,'customers':customers}

@app.post('/api/users',status_code=201)
def create_user(v:ManagedUser,x_user:str=Depends(current_user)):
    actor,_=require(x_user,{'admin','owner'})
    username,display=validate_account(v.username,v.display_name,v.password)
    if v.role not in ASSIGNABLE_ROLES: raise HTTPException(400,'Choose Sales, Production, or Auditor role')
    salt,password_hash=password_credentials(v.password)
    with conn() as c:
        try:
            c.execute('INSERT INTO users(user_id,role,display,password_salt,password_hash,is_demo) VALUES(?,?,?,?,?,0)',(username,v.role,display,salt,password_hash))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409,'That username is already in use') from exc
        log(c,actor,'user_created',username,{'role':v.role,'display':display})
        account=c.execute('SELECT user_id,role,display,is_demo,created_at FROM users WHERE user_id=?',(username,)).fetchone()
    return dict(account)

@app.put('/api/users/{username}/customers')
def assign_user_customers(username:str,v:CustomerAssignment,x_user:str=Depends(current_user)):
    actor,_=require(x_user,{'admin','owner'})
    username=username.strip().lower()
    customer_ids=list(dict.fromkeys(v.customer_ids))
    with conn() as c:
        c.execute('BEGIN IMMEDIATE')
        account=c.execute('SELECT role FROM users WHERE user_id=?',(username,)).fetchone()
        if not account: raise HTTPException(404,'User not found')
        if account['role']!='salesman': raise HTTPException(400,'Customer routes can only be assigned to Sales users')
        if len(customer_ids)!=len(v.customer_ids): raise HTTPException(400,'Customer IDs must be unique')
        if customer_ids:
            placeholders=','.join('?' for _ in customer_ids)
            found=c.execute(f'SELECT id FROM customers WHERE id IN ({placeholders})',customer_ids).fetchall()
            if len(found)!=len(customer_ids): raise HTTPException(400,'One or more customers were not found')
        c.execute('UPDATE customers SET salesperson=NULL WHERE salesperson=?',(username,))
        for customer_id in customer_ids:
            c.execute('UPDATE customers SET salesperson=? WHERE id=?',(username,customer_id))
        log(c,actor,'sales_route_assigned',username,{'customer_ids':customer_ids})
    return {'user':username,'customer_ids':customer_ids}

@app.post('/api/logout')
def logout(request:Request,x_user:str=Depends(current_user)):
    token=request.cookies.get('oa_session')
    if not token: raise HTTPException(401,'Please sign in')
    with conn() as c: c.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
    response=JSONResponse({'ok':True})
    response.delete_cookie('oa_session',httponly=True,samesite='lax',secure=os.getenv('ORDER_AUDIT_COOKIE_SECURE','0')=='1')
    return response

@app.get('/api/me')
def me(x_user:str=Depends(current_user)):
    with conn() as c: account=c.execute('SELECT user_id,role,display,is_demo FROM users WHERE user_id=?',(x_user,)).fetchone()
    if not account: raise HTTPException(401,'Unknown user')
    return {'user':account['user_id'],'role':account['role'],'display':account['display'],'is_demo':bool(account['is_demo'])}
@app.post('/api/reset')
def reset(x_user:str=Depends(current_user)):
    require(x_user,{'admin','owner'})
    with conn() as c:
        c.execute('BEGIN IMMEDIATE')
        for table in ('payments','orders','production','movements','audit'):
            c.execute(f'DELETE FROM {table}')
        c.execute('UPDATE materials SET rate_paise=CASE id WHEN 1 THEN 4200 WHEN 2 THEN 14000 WHEN 3 THEN 20000 WHEN 4 THEN 250 WHEN 5 THEN 1500 ELSE rate_paise END')
        log(c,x_user,'benchmark_reset','benchmark',{'message':'Transactions cleared; benchmark opening balances restored'})
    return {'ok':True,'message':'Benchmark dataset reset'}
@app.get('/api/summary')
def summary(x_user:str=Depends(current_user)):
    u,r=role(x_user)
    with conn() as c:
        result={'stock':fg_stock(c,1),'role':r}
        if r in {'admin','owner'}:
            result.update({
                'orders_today':c.execute("SELECT COUNT(*) FROM orders WHERE date(created_at)=date('now')").fetchone()[0],
                'pending_orders':c.execute("SELECT COUNT(*) FROM orders WHERE status='submitted'").fetchone()[0],
                'outstanding_paise':c.execute('SELECT COALESCE(SUM(o.total_paise-p.paid),0) FROM orders o LEFT JOIN (SELECT order_id,SUM(amount_paise) paid FROM payments GROUP BY order_id) p ON p.order_id=o.id WHERE o.status IN ("invoiced","dispatched")').fetchone()[0],
            })
        if r in {'admin','owner','production'}:
            result['raw_stock']={m['name']:round(material_stock(c,m['id']),2) for m in c.execute('SELECT * FROM materials')}
        return result
@app.get('/api/masters')
def masters(x_user:str=Depends(current_user)):
    u,r=role(x_user)
    with conn() as c:
        customers=c.execute('SELECT * FROM customers WHERE salesperson=?',(u,)).fetchall() if r=='salesman' else c.execute('SELECT * FROM customers').fetchall()
        return {'products':[dict(x) for x in c.execute('SELECT * FROM products')], 'customers':[dict(x) for x in customers], 'materials':[] if r=='salesman' else [dict(x) for x in c.execute('SELECT * FROM materials')], 'bom':[] if r=='salesman' else [dict(x) for x in c.execute('SELECT b.*,m.name material_name,m.rate_paise FROM bom b JOIN materials m ON m.id=b.material_id')]}
@app.get('/api/orders')
def orders(x_user:str=Depends(current_user)):
    u,r=require(x_user,{'admin','owner','salesman'})
    with conn() as c:
        reserved=sum(json.loads(item['lines_json'])[0]['quantity'] for item in c.execute('SELECT lines_json FROM orders WHERE status="approved"'))
        available=max(0,fg_stock(c,1)-reserved)
        rows=c.execute('''SELECT o.*,c.name customer,c.state,COALESCE(p.paid_paise,0) paid_paise
            FROM orders o JOIN customers c ON c.id=o.customer_id
            LEFT JOIN (SELECT order_id,SUM(amount_paise) paid_paise FROM payments GROUP BY order_id) p ON p.order_id=o.id
            ORDER BY o.id DESC''').fetchall()
        return [dict(z,lines=json.loads(z['lines_json']),outstanding_paise=max(0,z['total_paise']-z['paid_paise']),stock_available=available,stock_shortage=max(0,json.loads(z['lines_json'])[0]['quantity']-available)) for z in rows if r!='salesman' or z['salesperson']==u]
@app.post('/api/orders')
def create_order(v:OrderIn,x_user:str=Depends(current_user)):
    u,r=require(x_user,{'salesman','admin','owner'})
    if v.quantity<=0: raise HTTPException(400,'Order quantity must be positive')
    with conn() as c:
        customer=c.execute('SELECT * FROM customers WHERE id=?',(v.customer_id,)).fetchone()
        if not customer: raise HTTPException(404,'Customer not found')
        if r=='salesman' and customer['salesperson']!=u: raise HTTPException(403,'Customer belongs to another salesperson')
        p=c.execute('SELECT * FROM products WHERE id=1').fetchone(); qty=v.quantity
        line={'product_id':1,'name':p['name'],'quantity':qty,'unit_price_paise':p['price_paise']}
        sub=qty*p['price_paise']; tax=(sub*p['gst_rate']+50)//100
        cur=c.execute('INSERT INTO orders(customer_id,salesperson,status,lines_json,subtotal_paise,gst_paise,total_paise) VALUES(?,?,?,?,?,?,?)',(customer['id'],u,'submitted',json.dumps([line]),sub,tax,sub+tax))
        log(c,u,'order_submitted',cur.lastrowid,{'qty':qty,'customer':customer['name']})
        return {'id':cur.lastrowid,'status':'submitted','stock_available':fg_stock(c,1),'shortage':max(0,qty-fg_stock(c,1))}
@app.post('/api/orders/{oid}/decision')
def decision(oid:int,v:Decision,x_user:str=Depends(current_user)):
    u,_=require(x_user,{'admin','owner'})
    with conn() as c:
        c.execute('BEGIN IMMEDIATE')
        o=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
        if not o or o['status']!='submitted': raise HTTPException(404,'Pending order not found')
        lines=json.loads(o['lines_json']); qty=v.quantity if v.quantity is not None else lines[0]['quantity']
        if qty<=0: raise HTTPException(400,'Order quantity must be positive')
        unit_price=v.unit_price_paise if v.unit_price_paise is not None else lines[0]['unit_price_paise']
        if unit_price<=0: raise HTTPException(400,'Unit price must be greater than zero')
        product=c.execute('SELECT * FROM products WHERE id=?',(lines[0]['product_id'],)).fetchone()
        lines[0]['quantity']=qty; lines[0]['unit_price_paise']=unit_price
        sub=qty*unit_price; tax=(sub*product['gst_rate']+50)//100
        reserved=sum(json.loads(item['lines_json'])[0]['quantity'] for item in c.execute('SELECT lines_json FROM orders WHERE status="approved"'))
        stock=max(0,fg_stock(c,product['id'])-reserved)
        shortage=max(0,qty-stock)
        if v.approved and shortage: raise HTTPException(409,f'Insufficient stock: {quantity_text(shortage)} packets short')
        status='approved' if v.approved else 'rejected'
        c.execute('UPDATE orders SET status=?,lines_json=?,subtotal_paise=?,gst_paise=?,total_paise=? WHERE id=?',(status,json.dumps(lines),sub,tax,sub+tax,oid))
        log(c,u,status,oid,{'quantity':qty,'unit_price_paise':unit_price,'stock_available':stock})
        return {'status':status,'stock':stock,'shortage':shortage,'total_paise':sub+tax}
@app.post('/api/orders/{oid}/dispatch')
def dispatch(oid:int,x_user:str=Depends(current_user)):
    u,_=require(x_user,{'admin','owner'})
    with conn() as c:
        c.execute('BEGIN IMMEDIATE')
        o=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
        if not o or o['status']!='approved': raise HTTPException(409,'Order must be approved before dispatch')
        q=json.loads(o['lines_json'])[0]['quantity']; stock=fg_stock(c,1)
        if q>stock: raise HTTPException(409,f'Insufficient stock: {quantity_text(q-stock)} packets short')
        today=date.today()
        fy_start=today.year if today.month>=4 else today.year-1
        prefix=f'FY{fy_start%100:02d}-{(fy_start+1)%100:02d}'
        invoice_count=c.execute('SELECT COUNT(*) FROM orders WHERE invoice_no LIKE ?',(prefix+'/%',)).fetchone()[0]
        invoice=f'{prefix}/{invoice_count+1:04d}'
        invoiced_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute('INSERT INTO movements(item_type,item_id,qty,source_type,source_id,note) VALUES("product",1,?,?,?,?)',(-q,'dispatch',str(oid),'Invoice dispatch'))
        c.execute('UPDATE orders SET status="dispatched",invoice_no=?,invoiced_at=? WHERE id=?',(invoice,invoiced_at,oid)); log(c,u,'dispatch',invoice,{'qty':q})
        return {'status':'dispatched','invoice_no':invoice,'stock':fg_stock(c,1)}
@app.get('/api/orders/{oid}/invoice')
def invoice(oid:int,x_user:str=Depends(current_user)):
    u,r=require(x_user,{'admin','owner','auditor','salesman'})
    with conn() as c:
        o=c.execute('SELECT o.*,c.name,c.state,c.gstin,c.salesperson,p.name product_name,p.hsn,p.gst_rate FROM orders o JOIN customers c ON c.id=o.customer_id JOIN products p ON p.id=1 WHERE o.id=?',(oid,)).fetchone()
        if not o or not o['invoice_no'] or (r=='salesman' and o['salesperson']!=u): raise HTTPException(404,'Invoice not available')
        lines=json.loads(o['lines_json']); same=o['state']=='Tamil Nadu'; tax=o['gst_paise']; cgst=tax//2; sgst=tax-cgst
        line=lines[0]
        html=f'''<html><meta charset="utf-8"><style>body{{font:16px Arial;margin:48px;color:#172b28}}h1{{color:#146b51}}table{{width:100%;border-collapse:collapse}}td,th{{padding:12px;border-bottom:1px solid #ddd;text-align:left}}</style><h1>ANNAM FOODS</h1><h2>TAX INVOICE</h2><p>Invoice: {o['invoice_no']} &nbsp; Date: {(o['invoiced_at'] or o['created_at'])[:10]}</p><p>Bill to: {o['name']} | GSTIN: {o['gstin']} | Place of supply: {o['state']}</p><table><tr><th>Item</th><th>HSN</th><th>Qty</th><th>Rate</th><th>Taxable</th></tr><tr><td>{o['product_name']}</td><td>{o['hsn']}</td><td>{line['quantity']}</td><td>₹{line['unit_price_paise']/100:.2f}</td><td>₹{o['subtotal_paise']/100:.2f}</td></tr></table><p>{'CGST' if same else 'IGST'}: ₹{(cgst if same else tax)/100:.2f} {' | SGST: ₹'+format(sgst/100,'.2f') if same else ''}</p><h2>Total: ₹{o['total_paise']/100:.2f}</h2><p>Prototype invoice for internship evaluation; verify statutory requirements before production use.</p></html>'''
        return HTMLResponse(html,headers={'Content-Disposition':f'attachment; filename="invoice-{oid}.html"'})
@app.get('/api/orders/{oid}/invoice.pdf')
def invoice_pdf(oid:int,x_user:str=Depends(current_user)):
    u,r=require(x_user,{'admin','owner','auditor','salesman'})
    with conn() as c:
        o=c.execute('SELECT o.*,c.name,c.state,c.gstin,c.salesperson,p.name product_name,p.hsn,p.gst_rate FROM orders o JOIN customers c ON c.id=o.customer_id JOIN products p ON p.id=1 WHERE o.id=?',(oid,)).fetchone()
        if not o or not o['invoice_no'] or (r=='salesman' and o['salesperson']!=u): raise HTTPException(404,'Invoice not available')
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        buf=io.BytesIO(); pdf=canvas.Canvas(buf,pagesize=A4); w,h=A4
        pdf.setFillColorRGB(.08,.35,.26); pdf.setFont('Helvetica-Bold',22); pdf.drawString(48,h-54,'ANNAM FOODS')
        pdf.setFillColorRGB(.12,.17,.15); pdf.setFont('Helvetica-Bold',15); pdf.drawString(48,h-92,'TAX INVOICE')
        lines=json.loads(o['lines_json']); line=lines[0]; same=o['state']=='Tamil Nadu'; tax=o['gst_paise']; cgst=tax//2; sgst=tax-cgst
        entries=[('Invoice number',o['invoice_no']),('Invoice date',(o['invoiced_at'] or o['created_at'])[:10]),('Bill to',o['name']),('GSTIN',o['gstin']),('Place of supply',o['state']),('Item',f"{o['product_name']} (HSN {o['hsn']})"),('Quantity',f"{line['quantity']} packets"),('Rate',f"INR {line['unit_price_paise']/100:.2f}"),('Taxable value',f"INR {o['subtotal_paise']/100:.2f}")]
        yy=h-135
        for label,val in entries:
            pdf.setFont('Helvetica-Bold',10);pdf.drawString(48,yy,label);pdf.setFont('Helvetica',10);pdf.drawString(190,yy,str(val));yy-=25
        yy-=6;pdf.line(48,yy,w-48,yy);yy-=25
        pdf.setFont('Helvetica',10)
        if same:
            pdf.drawString(48,yy,f'CGST {o["gst_rate"]/2:g}%: INR {cgst/100:.2f}'); yy-=20;pdf.drawString(48,yy,f'SGST {o["gst_rate"]/2:g}%: INR {sgst/100:.2f}')
        else: pdf.drawString(48,yy,f'IGST {o["gst_rate"]}%: INR {tax/100:.2f}')
        yy-=34;pdf.setFont('Helvetica-Bold',14);pdf.drawString(48,yy,f"Invoice total: INR {o['total_paise']/100:.2f}")
        pdf.setFont('Helvetica',8);pdf.drawString(48,42,'Prototype invoice for internship evaluation. Verify current statutory requirements before production use.')
        pdf.save();buf.seek(0)
        return StreamingResponse(buf,media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="invoice-{oid}.pdf"'})
@app.post('/api/orders/{oid}/payments')
def payment(oid:int,v:Payment,x_user:str=Depends(current_user)):
    u,_=require(x_user,{'admin','owner'})
    if not v.amount_rupees.is_finite(): raise HTTPException(400,'Payment must be a finite amount')
    amount=rupees_to_paise(v.amount_rupees)
    if amount<=0: raise HTTPException(400,'Payment must be positive')
    with conn() as c:
        c.execute('BEGIN IMMEDIATE')
        order=c.execute('SELECT total_paise FROM orders WHERE id=? AND status IN ("dispatched","invoiced")',(oid,)).fetchone()
        if not order: raise HTTPException(404,'Dispatched invoice not found')
        paid=c.execute('SELECT COALESCE(SUM(amount_paise),0) FROM payments WHERE order_id=?',(oid,)).fetchone()[0]
        outstanding=order['total_paise']-paid
        if amount>outstanding: raise HTTPException(409,f'Payment exceeds the outstanding balance of ₹{max(0,outstanding)/100:.2f}')
        c.execute('INSERT INTO payments(order_id,amount_paise) VALUES(?,?)',(oid,amount)); log(c,u,'payment',oid,{'amount_paise':amount})
        return {'ok':True}
@app.post('/api/purchases/flour')
def purchase(v:Purchase,x_user:str=Depends(current_user)):
    u,_=require(x_user,{'production','admin','owner'})
    if not v.qty.is_finite() or not v.unit_price_rupees.is_finite() or v.qty<=0 or v.unit_price_rupees<=0: raise HTTPException(400,'Quantity and unit price must be positive finite values')
    new_rate=rupees_to_paise(v.unit_price_rupees)
    with conn() as c:
        c.execute('BEGIN IMMEDIATE')
        old_qty=material_stock(c,1); old_rate=c.execute('SELECT rate_paise FROM materials WHERE id=1').fetchone()[0]
        new_average=weighted_average_rate_paise(old_qty,old_rate,v.qty,new_rate)
        purchase_count=c.execute('SELECT COUNT(*) FROM movements WHERE source_type="purchase"').fetchone()[0]+1
        purchase_id=f'PUR-{purchase_count:03d}'
        c.execute('INSERT INTO movements(item_type,item_id,qty,source_type,source_id,note) VALUES("material",1,?,"purchase",?,?)',(float(v.qty),purchase_id,f'Flour purchase @ ₹{v.unit_price_rupees}/kg'))
        c.execute('UPDATE materials SET rate_paise=? WHERE id=1',(new_average,))
        log(c,u,'purchase',purchase_id,{'flour_kg':str(v.qty),'rate_paise':new_rate,'weighted_average_rate_paise':new_average})
        return {'flour_stock':material_stock(c,1)}
@app.post('/api/production/run')
def production(v:Run,x_user:str=Depends(current_user)):
    u,_=require(x_user,{'production','admin','owner'})
    quantities=(v.flour,v.oil,v.spice)
    costs=(v.labour_rupees,v.utilities_rupees)
    if any(not q.is_finite() or q<0 for q in quantities) or any(not cost.is_finite() or cost<0 for cost in costs) or min(v.actual_output,v.damaged_pouches,v.cartons_used)<0:
        raise HTTPException(400,'Production quantities and costs must be finite and non-negative')
    if v.flour<=0 or v.actual_output<=0: raise HTTPException(400,'A production run needs flour and at least one good packet')
    with conn() as c:
        c.execute('BEGIN IMMEDIATE')
        qtys={1:float(v.flour),2:float(v.oil),3:float(v.spice),4:v.actual_output+v.damaged_pouches,5:v.cartons_used}
        for mid,q in qtys.items():
            if q>material_stock(c,mid): raise HTTPException(409,f'Insufficient {c.execute("SELECT name FROM materials WHERE id=?",(mid,)).fetchone()[0]} stock')
        product=c.execute('SELECT expected_batch_qty FROM products WHERE id=1').fetchone()
        bom_rows=c.execute('SELECT material_id,qty FROM bom WHERE product_id=1').fetchall()
        bom={row['material_id']:Decimal(str(row['qty'])) for row in bom_rows}
        if not bom.get(1) or product['expected_batch_qty']<=0: raise HTTPException(500,'Murukku BOM is missing its flour quantity or expected yield')
        batches=v.flour/bom[1]
        expected=int((batches*product['expected_batch_qty']).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
        if expected<=0: raise HTTPException(400,'Flour issue is too small to produce one expected packet')
        rates={row['id']:row['rate_paise'] for row in c.execute('SELECT id,rate_paise FROM materials')}
        exact_cost=sum((Decimal(str(qtys[mid]))*Decimal(rates[mid]) for mid in qtys),Decimal(0))
        cost=int(exact_cost.quantize(Decimal('1'),rounding=ROUND_HALF_UP))
        labour=rupees_to_paise(v.labour_rupees); utilities=rupees_to_paise(v.utilities_rupees)
        cur=c.execute('INSERT INTO production(product_id,expected_qty,actual_qty,issued_json,damaged_pouches,cartons_used,labour_paise,utilities_paise,material_cost_paise) VALUES(1,?,?,?,?,?,?,?,?)',(expected,v.actual_output,json.dumps(qtys),v.damaged_pouches,v.cartons_used,labour,utilities,cost))
        rid=cur.lastrowid
        for mid,q in qtys.items(): c.execute('INSERT INTO movements(item_type,item_id,qty,source_type,source_id,note) VALUES("material",?, ?,"production",?,?)',(mid,-q,str(rid),'Production issue'))
        c.execute('INSERT INTO movements(item_type,item_id,qty,source_type,source_id,note) VALUES("product",1,?,"production",?,"Good packets produced")',(v.actual_output,str(rid)))
        log(c,u,'production_run',rid,{'expected':expected,'actual':v.actual_output,'issued':qtys})
        return run_view(c,rid)
def run_view(c,rid):
    r=c.execute('SELECT * FROM production WHERE id=?',(rid,)).fetchone(); expected=r['expected_qty']; actual=r['actual_qty']; issued=json.loads(r['issued_json'])
    batch_qty=c.execute('SELECT expected_batch_qty FROM products WHERE id=?',(r['product_id'],)).fetchone()['expected_batch_qty']
    bom_rows=c.execute('SELECT b.material_id,b.qty,m.name FROM bom b JOIN materials m ON m.id=b.material_id WHERE b.product_id=?',(r['product_id'],)).fetchall()
    scale=expected/batch_qty if batch_qty else 0
    variances={}
    for row in bom_rows:
        want=float(row['qty'])*scale; got=issued.get(str(row['material_id']),0)
        delta=0 if not want else (got-want)/want*100
        variances[row['name']]={'planned':round(want,2),'actual':got,'percent':round(delta,2),'flagged':abs(delta)>3}
    y=(actual-expected)/expected*100 if expected else 0
    total=r['material_cost_paise']+r['labour_paise']+r['utilities_paise']
    return {'id':rid,'expected':expected,'actual':actual,'yield_variance_pct':round(y,2),'yield_flagged':abs(y)>3,'consumption':variances,'material_cost_paise':r['material_cost_paise'],'overheads_paise':r['labour_paise']+r['utilities_paise'],'total_cost_paise':total,'cost_per_packet_paise':round(total/actual) if actual else 0,'stock':{'flour':material_stock(c,1),'oil':material_stock(c,2),'spice':material_stock(c,3),'pouches':material_stock(c,4),'cartons':material_stock(c,5),'finished_goods':fg_stock(c,1)}}
@app.get('/api/production/latest')
def latest_run(x_user:str=Depends(current_user)):
    require(x_user,{'admin','owner','production','auditor'})
    with conn() as c:
        r=c.execute('SELECT id FROM production ORDER BY id DESC LIMIT 1').fetchone(); return run_view(c,r['id']) if r else None
@app.get('/api/stock')
def stock(x_user:str=Depends(current_user)):
    _,r=role(x_user)
    with conn() as c:
        materials=[dict(m,closing=round(material_stock(c,m['id']),2)) for m in c.execute('SELECT * FROM materials')]
        ledger=[dict(m) for m in c.execute('SELECT * FROM movements ORDER BY id DESC')]
        return {'materials':[] if r=='salesman' else materials, 'products':[dict(p,closing=fg_stock(c,p['id'])) for p in c.execute('SELECT * FROM products')], 'ledger':[] if r=='salesman' else ledger}
@app.get('/api/reports')
def reports(x_user:str=Depends(current_user),start_date:date|None=None,end_date:date|None=None):
    require(x_user,{'auditor','admin','owner'})
    if start_date and end_date and start_date>end_date: raise HTTPException(400,'Start date must not be after end date')
    with conn() as c:
        conditions=['o.invoice_no IS NOT NULL']; params=[]
        if start_date: conditions.append('date(COALESCE(o.invoiced_at,o.created_at))>=?'); params.append(start_date.isoformat())
        if end_date: conditions.append('date(COALESCE(o.invoiced_at,o.created_at))<=?'); params.append(end_date.isoformat())
        inv=c.execute('SELECT o.*,c.name customer,c.state FROM orders o JOIN customers c ON c.id=o.customer_id WHERE '+' AND '.join(conditions)+' ORDER BY o.id',params).fetchall()
        rows=[]
        ageing={}
        as_of=end_date or date.today()
        for o in inv:
            payment_sql='SELECT COALESCE(SUM(amount_paise),0) FROM payments WHERE order_id=?'
            payment_params=[o['id']]
            if end_date:
                payment_sql+=' AND date(created_at)<=?'; payment_params.append(end_date.isoformat())
            paid=c.execute(payment_sql,payment_params).fetchone()[0]
            due=max(0,o['total_paise']-paid)
            invoice_date=date.fromisoformat((o['invoiced_at'] or o['created_at'])[:10])
            age_days=max(0,(as_of-invoice_date).days)
            bucket='Paid' if due==0 else 'Current' if age_days==0 else '1-30 days' if age_days<=30 else '31-60 days' if age_days<=60 else '61+ days'
            rows.append({'invoice':o['invoice_no'],'invoice_date':invoice_date.isoformat(),'customer':o['customer'],'state':o['state'],'status':o['status'],'taxable_paise':o['subtotal_paise'],'gst_paise':o['gst_paise'],'total_paise':o['total_paise'],'paid_paise':paid,'outstanding_paise':due,'age_days':age_days,'ageing_bucket':bucket})
            if due:
                entry=ageing.setdefault(o['customer'],{'customer':o['customer'],'current_paise':0,'1_30_days_paise':0,'31_60_days_paise':0,'61_plus_days_paise':0,'total_paise':0})
                age_key='current_paise' if age_days==0 else '1_30_days_paise' if age_days<=30 else '31_60_days_paise' if age_days<=60 else '61_plus_days_paise'
                entry[age_key]+=due; entry['total_paise']+=due
        return {'sales':rows,'ageing':list(ageing.values()),'gst':{'taxable_paise':sum(z['taxable_paise'] for z in rows),'gst_paise':sum(z['gst_paise'] for z in rows)},'stock':stock(x_user),'production':run_view(c,c.execute('SELECT id FROM production ORDER BY id DESC LIMIT 1').fetchone()['id']) if c.execute('SELECT COUNT(*) FROM production').fetchone()[0] else None}
@app.get('/api/reports.csv')
def reports_csv(x_user:str=Depends(current_user),start_date:date|None=None,end_date:date|None=None):
    require(x_user,{'auditor','admin','owner'})
    data=reports(x_user,start_date,end_date); f=io.StringIO(); w=csv.DictWriter(f,fieldnames=list(data['sales'][0].keys()) if data['sales'] else ['invoice','invoice_date','customer','state','status','taxable_paise','gst_paise','total_paise','paid_paise','outstanding_paise','age_days','ageing_bucket']); w.writeheader();w.writerows(data['sales']); f.seek(0)
    return StreamingResponse(iter([f.getvalue()]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="sales-register.csv"'})
@app.get('/api/ledger.csv')
def ledger_csv(x_user:str=Depends(current_user)):
    require(x_user,{'auditor','admin','owner'})
    rows=stock(x_user)['ledger']; f=io.StringIO(); w=csv.DictWriter(f,fieldnames=['id','item_type','item_id','qty','source_type','source_id','note','created_at']); w.writeheader();w.writerows(rows); f.seek(0)
    return StreamingResponse(iter([f.getvalue()]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="stock-ledger.csv"'})
@app.get('/api/reports.pdf')
def reports_pdf(x_user:str=Depends(current_user),start_date:date|None=None,end_date:date|None=None):
    require(x_user,{'auditor','admin','owner'})
    data=reports(x_user,start_date,end_date)
    from xml.sax.saxutils import escape
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

    def amount(paise): return f'INR {paise//100}.{paise%100:02d}'
    buf=io.BytesIO()
    doc=SimpleDocTemplate(buf,pagesize=landscape(A4),rightMargin=15*mm,leftMargin=15*mm,topMargin=14*mm,bottomMargin=14*mm)
    styles=getSampleStyleSheet()
    elements=[Paragraph('ANNAM FOODS · MONTHLY AUDIT REPORT',styles['Title']),Paragraph(f"Period: {start_date or 'all dates'} to {end_date or 'today'}",styles['Normal']),Spacer(1,8)]
    elements.append(Paragraph(f"Taxable sales: {amount(data['gst']['taxable_paise'])} &nbsp;&nbsp; Output GST: {amount(data['gst']['gst_paise'])} &nbsp;&nbsp; Outstanding: {amount(sum(row['outstanding_paise'] for row in data['sales']))}",styles['Normal']))
    elements.extend([Spacer(1,10),Paragraph('Sales and GST register',styles['Heading2'])])
    sales=[['Invoice','Date','Customer','State','Taxable','GST','Paid','Due']]
    sales.extend([[row['invoice'],row['invoice_date'],escape(row['customer']),escape(row['state']),amount(row['taxable_paise']),amount(row['gst_paise']),amount(row['paid_paise']),amount(row['outstanding_paise'])] for row in data['sales']])
    elements.append(LongTable(sales,repeatRows=1,colWidths=[62,62,110,85,78,70,70,70]))
    elements.extend([Spacer(1,10),Paragraph('Receivables ageing',styles['Heading2'])])
    ageing=[['Customer','Current','1-30 days','31-60 days','61+ days','Total']]
    ageing.extend([[escape(row['customer']),amount(row['current_paise']),amount(row['1_30_days_paise']),amount(row['31_60_days_paise']),amount(row['61_plus_days_paise']),amount(row['total_paise'])] for row in data['ageing']])
    if len(ageing)==1: ageing.append(['No outstanding invoices','','','','',''])
    elements.append(LongTable(ageing,repeatRows=1,colWidths=[150,90,90,90,90,90]))
    elements.extend([Spacer(1,10),Paragraph('Current stock summary',styles['Heading2'])])
    stock_rows=[['Item','Closing balance','Unit']]
    stock_rows.extend([[escape(row['name']),str(row['closing']),escape(row['unit'])] for row in data['stock']['materials']])
    stock_rows.extend([[escape(row['name']),str(row['closing']),'packets'] for row in data['stock']['products']])
    elements.append(LongTable(stock_rows,repeatRows=1,colWidths=[270,130,100]))
    if data['production']:
        elements.extend([Spacer(1,10),Paragraph('Latest production run',styles['Heading2'])])
        run=data['production']
        elements.append(Paragraph(f"Run #{run['id']}: {run['actual']} good packets vs {run['expected']} expected; yield variance {run['yield_variance_pct']}%; cost per packet {amount(run['cost_per_packet_paise'])}.",styles['Normal']))
        variance=[['Material','Planned','Actual','Variance','Alert']]
        variance.extend([[escape(name),str(row['planned']),str(row['actual']),f"{row['percent']}%",'Flag' if row['flagged'] else 'Within'] for name,row in run['consumption'].items()])
        elements.append(LongTable(variance,repeatRows=1,colWidths=[190,100,100,100,100]))
    table_style=TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#17694f')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),8),('GRID',(0,0),(-1,-1),.35,colors.HexColor('#dce7e1')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f4f8f5')]),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)])
    for element in elements:
        if isinstance(element,LongTable): element.setStyle(table_style)
    doc.build(elements);buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]),media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="monthly-audit-report.pdf"'})

app.mount('/',StaticFiles(directory=HERE.parent/'frontend',html=True),name='frontend')
