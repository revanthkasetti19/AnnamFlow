const users=['admin','sales-a','sales-b','production','auditor','owner'];
const labels={admin:'Factory Admin', 'sales-a':'Salesman A','sales-b':'Salesman B',production:'Production Supervisor',auditor:'Auditor',owner:'Owner'};
let user=null, userRole=null, userDisplay=null, userIsDemo=false, page='Overview', latest=null, paymentOrderId=null, paymentOutstandingPaise=0;
const today=new Date(), monthStart=new Date(today.getFullYear(),today.getMonth(),1);
const localDate=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
let reportStart=localDate(monthStart),reportEnd=localDate(today);
const navByRole={admin:[['Overview','⌂'],['Orders','▤'],['New Order','＋'],['Production','⚙'],['Inventory','▦'],['Reports','▧'],['Users','♙']],owner:[['Overview','⌂'],['Orders','▤'],['New Order','＋'],['Production','⚙'],['Inventory','▦'],['Reports','▧'],['Users','♙']],salesman:[['Overview','⌂'],['New Order','＋'],['My Orders','▤'],['Customers','♙']],production:[['Overview','⌂'],['Production','⚙'],['Inventory','▦']],auditor:[['Overview','⌂'],['Reports','▧'],['Inventory','▦']]};
function role(){return userRole}
async function api(url,method='GET',body){const r=await fetch('/api'+url,{method,credentials:'same-origin',headers:{'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});let d;try{d=await r.json()}catch{d={}}if(!r.ok){if(r.status===401&&!url.startsWith('/login'))showLogin(d.detail||'Please sign in again');const error=Error(d.detail||'Something went wrong');error.status=r.status;throw error}return d}
function escapeHtml(value){return String(value||'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]))}
function money(p){return '₹'+(Number(p||0)/100).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2})}
function rupeesToPaise(value){const match=String(value).trim().match(/^(\d+)(?:\.(\d{1,2}))?$/);return match?Number(match[1])*100+Number((match[2]||'').padEnd(2,'0')):null}
function notify(s){let t=document.querySelector('#toast');t.textContent=s;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),3000)}
function setPage(p){page=p;render()}
function status(s){let cl=s==='dispatched'?'':s==='rejected'?'red':s==='submitted'?'warn':'gray';return `<span class="pill ${cl}">${s}</span>`}
function card(title,body,sub=''){return `<article class="card stat-card"><div class="stat-label">${title}</div><div class="stat-value">${body}</div><div class="stat-foot">${sub}</div></article>`}
async function render(){
 const r=role(), nav=navByRole[r]||navByRole.owner;
 document.querySelector('#nav').innerHTML=nav.map(([n,i])=>`<button type="button" class="${page===n?'active':''}" ${page===n?'aria-current="page"':''} onclick="setPage('${n}')"><span class="nav-ico" aria-hidden="true">${i}</span><span>${n}</span></button>`).join('');
 const display=labels[user]||userDisplay||user;
 document.querySelector('#userName').textContent=display;
 document.querySelector('#userRole').textContent=r==='admin'?'Administrator':r==='salesman'?'Field Sales':r==='production'?'Production':r==='auditor'?'Read only':'Owner';
 const profile=document.querySelector('#profile');
 const initials=({admin:'AF','sales-a':'SA','sales-b':'SB',production:'PS',auditor:'AU',owner:'OW'})[user]||(display.split(/\s+/).slice(0,2).map(part=>part[0]).join('').toUpperCase()||'U');
 profile.textContent=`${initials} ▾`;
 profile.title=userIsDemo?`Switch workspace role · current: ${display}`:`Account actions · ${display}`;
 profile.setAttribute('aria-label',userIsDemo?`Current role: ${display}. Switch workspace role.`:`Account actions for ${display}.`);
 document.querySelector('#resetBtn').hidden=!['admin','owner'].includes(r);
 document.querySelector('#sectionName').textContent=page;
 document.querySelector('#pageTitle').textContent=page==='Overview'?`Good morning, ${r==='salesman'?'sales team':'team'}`:page;
 document.querySelector('#currentDate').textContent=new Intl.DateTimeFormat('en-IN',{weekday:'long',year:'numeric',month:'long',day:'numeric'}).format(new Date()).toUpperCase();
 document.querySelector('#welcome').style.display=page==='Overview'?'flex':'none';
 const a=document.querySelector('#app');
 a.innerHTML='<div class="empty">Loading workspace…</div>';
 try{
  if(page==='Overview')a.innerHTML=await overview();
  else if(page==='Production')a.innerHTML=await productionPage();
  else if(page==='Orders'||page==='My Orders')a.innerHTML=await ordersPage();
  else if(page==='New Order')a.innerHTML=await newOrderPage();
  else if(page==='Inventory')a.innerHTML=await inventoryPage();
  else if(page==='Reports')a.innerHTML=await reportsPage();
  else if(page==='Customers')a.innerHTML=await customersPage();
  else if(page==='Users')a.innerHTML=await usersPage();
 }catch(e){a.innerHTML=`<div class="notice error"><b>Could not load this section.</b><p>${e.message}</p><button class="btn secondary" type="button" onclick="render()">Try again</button></div>`}
 if(!['admin','owner'].includes(r))a.querySelectorAll('button[onclick="resetDemo()"]').forEach(button=>button.hidden=true);
}
async function overview(){
 const r=role();
 const [s,ord,m,stock,lastRun,audit]=await Promise.all([
  api('/summary'),
  ['admin','owner','salesman'].includes(r)?api('/orders'):Promise.resolve([]),
  api('/masters'),
  api('/stock'),
  ['admin','owner','production','auditor'].includes(r)?api('/production/latest'):Promise.resolve(null),
  r==='auditor'?api('/reports'):Promise.resolve(null)
 ]);
 const pending=ord.filter(x=>x.status==='submitted').length;
 let roleCards;
 if(r==='salesman'){
  roleCards=`${card('MY OPEN ORDERS',pending,'Awaiting factory review')}${card('AVAILABLE MURUKKU',s.stock+' pkts','Finished goods on hand')}${card('CUSTOMERS',m.customers.filter(c=>c.salesperson===user).length,'Assigned to your route')}${card('TODAY’S SALES',money(ord.filter(x=>x.status==='dispatched').reduce((n,x)=>n+x.total_paise,0)),'Dispatched invoice value')}`;
 }else if(r==='production'){
  roleCards=`${card('MATERIAL ITEMS',stock.materials.length,'Tracked in the stock ledger')}${card('FINISHED STOCK',s.stock+' pkts','Murukku 200 g')}${card('LATEST YIELD',lastRun?`${lastRun.actual} / ${lastRun.expected}`:'—','Good packets vs expected')}${card('COST PER PACKET',lastRun?money(lastRun.cost_per_packet_paise):'—','Materials and run overheads')}`;
 }else if(r==='auditor'){
  roleCards=`${card('INVOICES',audit.sales.length,'In the available report range')}${card('TAXABLE SALES',money(audit.gst.taxable_paise),'Invoiced sales')}${card('OUTPUT GST',money(audit.gst.gst_paise),'Outward tax summary')}${card('RECEIVABLES',money(audit.sales.reduce((n,x)=>n+x.outstanding_paise,0)),'Outstanding on invoices')}`;
 }else{
  roleCards=`${card('ORDERS TODAY',s.orders_today,'Across both field routes')}${card('PENDING REVIEW',s.pending_orders,'Orders waiting for approval')}${card('FINISHED STOCK',s.stock+' pkts','Murukku 200 g available')}${card('RECEIVABLES',money(s.outstanding_paise),'Across dispatched invoices')}`;
 }
 const retailerOrder=ord.find(x=>x.customer_id===1);
 let steps;
 if(r==='salesman'){
  steps=[
   {label:'Place an order',detail:'Send a customer order to the factory',done:ord.length>0,page:'New Order'},
   {label:'Factory review',detail:'Track approval or rejection',done:ord.some(x=>x.status!=='submitted'),page:'My Orders'},
   {label:'Confirm dispatch',detail:'Follow the order through fulfilment',done:ord.some(x=>x.status==='dispatched'),page:'My Orders'},
   {label:'View your invoice',detail:'Download the invoice after dispatch',done:ord.some(x=>Boolean(x.invoice_no)),page:'My Orders'}
  ];
 }else if(r==='production'){
  steps=[
   {label:'Review material stock',detail:'Check raw and packaging balances',done:stock.materials.length>0,page:'Inventory'},
   {label:'Post production',detail:'Record output and raw-material issues',done:Boolean(lastRun),page:'Production'},
   {label:'Review planned vs actual',detail:'Inspect yield and consumption variance',done:Boolean(lastRun),page:'Production'},
   {label:'Reconcile movements',detail:'Trace production inputs and output',done:stock.ledger.length>0,page:'Inventory'}
  ];
 }else if(r==='auditor'){
  steps=[
   {label:'Review sales register',detail:'Check invoiced sales in the period',done:audit.sales.length>0,page:'Reports'},
   {label:'Reconcile GST',detail:'Review outward taxable value and tax',done:audit.sales.length>0,page:'Reports'},
   {label:'Check receivables ageing',detail:'Review customer balances by age',done:audit.ageing.length>0,page:'Reports'},
   {label:'Export audit pack',detail:'Download filtered CSV and PDF reports',done:true,page:'Reports'}
  ];
 }else{
  steps=[
   {label:'Receive flour',detail:'Post the benchmark flour receipt',done:stock.ledger.some(x=>x.source_type==='purchase'),page:'Production'},
   {label:'Post production',detail:'Record a batch and reconcile material use',done:Boolean(lastRun),page:'Production'},
   {label:'Dispatch Retailer A',detail:'Approve the order and create its invoice',done:retailerOrder?.status==='dispatched',page:'Orders'},
   {label:'Record a collection',detail:'Post a payment against the invoice',done:(retailerOrder?.paid_paise||0)>0,page:'Orders'}
  ];
 }
 const complete=steps.filter(x=>x.done).length,next=steps.find(x=>!x.done);
 const actionPage=next?.page||(r==='salesman'?'My Orders':r==='auditor'?'Reports':r==='production'?'Production':'Reports');
 const actionLabel=r==='salesman'?(actionPage==='New Order'?'Create an order':'Track my orders'):r==='production'?'Open production':r==='auditor'?'Open audit reports':next?`Continue: ${next.label}`:'View reports';
 const stepRows=steps.map((x,i)=>`<div class="workflow-step ${x.done?'is-complete':''}"><span class="step-index">${x.done?'✓':String(i+1).padStart(2,'0')}</span><div><b>${x.label}</b><small>${x.detail}</small></div><span class="step-state">${x.done?'Complete':'Next'}</span></div>`).join('');
 const isAuditor=r==='auditor';
 const recentRows=isAuditor
  ?audit.sales.slice(0,5).map(x=>`<tr><td><b>${x.invoice}</b></td><td>${x.customer}</td><td>${x.invoice_date}</td><td>${money(x.outstanding_paise)}</td><td>${status(x.status)}</td></tr>`).join('')
  :ord.slice(0,5).map(o=>`<tr><td><b>#${o.id}</b></td><td>${o.customer}</td><td>${o.lines[0].quantity} packets</td><td>${money(o.total_paise)}</td><td>${status(o.status)}</td></tr>`).join('');
 const emptyRecent=`<tr><td colspan="5" class="empty">${r==='production'?'Production activity is available in the Production and Inventory modules.':'No recent activity for this view.'}</td></tr>`;
 const recentTitle=isAuditor?'Recent invoices':'Recent orders';
 const recentSubtitle=isAuditor?'Invoiced sales and current customer balances':'Latest updates from the sales floor';
 const recentAction=isAuditor?'Reports':r==='production'?'Inventory':r==='salesman'?'My Orders':'Orders';
 const recentHeaders=isAuditor?'<th>INVOICE</th><th>CUSTOMER</th><th>DATE</th><th>DUE</th><th>STATUS</th>':'<th>ORDER</th><th>CUSTOMER</th><th>QUANTITY</th><th>VALUE</th><th>STATUS</th>';
 return `<div class="grid stats">${roleCards}</div>
 <div class="grid two dashboard-grid">
  <div class="card"><div class="section-head"><div><h2>${recentTitle}</h2><p>${recentSubtitle}</p></div><button class="btn secondary" type="button" onclick="setPage('${recentAction}')">${isAuditor?'Open reports':r==='production'?'View stock':'View all'}</button></div><div class="table-wrap"><table><thead><tr>${recentHeaders}</tr></thead><tbody>${recentRows||emptyRecent}</tbody></table></div></div>
  <div class="card workflow-card"><div class="section-head"><div><h2>Workflow progress</h2><p>Live status from your role-specific records</p></div><span class="pill">${complete} / ${steps.length}</span></div><div class="progress" role="progressbar" aria-label="Workflow progress" aria-valuemin="0" aria-valuemax="${steps.length}" aria-valuenow="${complete}"><i style="width:${complete/steps.length*100}%"></i></div><div class="workflow-list">${stepRows}</div><button class="btn soft workflow-action" type="button" onclick="setPage('${actionPage}')">${actionLabel} →</button></div>
 </div>`;
}
async function productionPage(){let s=await api('/stock'),last=await api('/production/latest');latest=last;let mat=s.materials.map(x=>`<tr><td>${x.name}</td><td>${x.closing} ${x.unit}</td><td>${money(x.rate_paise)}/${x.unit}</td></tr>`).join('');let result=last?`<div class="notice ${last.yield_flagged?'warning':''}"><b>Run #${last.id} · ${last.actual} / ${last.expected} packets · yield ${last.yield_variance_pct}%</b><br>${last.yield_flagged?'Yield is outside the 3% tolerance.':'Yield within tolerance.'} Cost: <b>${money(last.cost_per_packet_paise)} per packet</b> (weighted average materials + run overhead).</div><div class="table-wrap"><table><thead><tr><th>MATERIAL</th><th>PLANNED</th><th>ACTUAL</th><th>VARIANCE</th><th>CHECK</th></tr></thead><tbody>${Object.entries(last.consumption).map(([n,x])=>`<tr><td>${n}</td><td>${x.planned}</td><td>${x.actual}</td><td>${x.percent>0?'+':''}${x.percent}%</td><td>${x.flagged?'<span class="pill red">Flag</span>':'<span class="pill">Within</span>'}</td></tr>`).join('')}</tbody></table></div><div class="cost-box"><div><small>MATERIAL COST</small><b>${money(last.material_cost_paise)}</b></div><div><small>LABOUR + GAS/POWER</small><b>${money(last.overheads_paise)}</b></div><div><small>TOTAL RUN COST</small><b>${money(last.total_cost_paise)}</b></div></div>`:'<div class="empty">No runs recorded. Start with the benchmark below.</div>';
return `<div class="section-head"><div><h2>Production run</h2><p>BOM driven consumption with automatic stock posting</p></div><button class="btn secondary" onclick="resetDemo()">Reset benchmark</button></div><div class="grid two"><div class="card"><div class="section-head"><div><h2>Record the benchmark</h2><p>Murukku 200 g · standard batch yield 200</p></div></div><div class="notice">The benchmark starts with a purchase of <b>60 kg flour at ₹45/kg</b>. Record it before submitting the production run.</div><div class="form-row"><div class="field"><label>Flour purchase (kg)</label><input id="purchaseQty" type="number" value="60"></div><div class="field"><label>Purchase rate (₹/kg)</label><input id="purchaseRate" type="number" value="45.00" min="0.01" step="0.01"></div><button class="btn soft" onclick="buyFlour()">Record purchase</button></div><div class="split"><div class="field"><label>Flour issued (kg)</label><input id="flour" type="number" value="40" step=".1"></div><div class="field"><label>Oil issued (L)</label><input id="oil" type="number" value="10.5" step=".1"></div><div class="field"><label>Spice mix issued (kg)</label><input id="spice" type="number" value="1.2" step=".1"></div><div class="field"><label>Good packets produced</label><input id="output" type="number" value="188"></div><div class="field"><label>Damaged pouches</label><input id="damaged" type="number" value="6"></div><div class="field"><label>Cartons used</label><input id="cartons" type="number" value="9"></div><div class="field"><label>Labour cost (₹)</label><input id="labour" type="number" value="1200.00" step=".01"></div><div class="field"><label>Gas / power (₹)</label><input id="utilities" type="number" value="600.00" step=".01"></div></div><button class="btn" onclick="saveRun()">Post production run</button></div><div class="card"><div class="section-head"><div><h2>Run analysis</h2><p>Planned vs actual · 3% variance tolerance</p></div></div>${result}</div></div><div class="card" style="margin-top:15px"><div class="section-head"><div><h2>Current raw material stock</h2><p>Balances reconcile from the movement ledger</p></div><button class="btn secondary" onclick="setPage('Inventory')">Open stock ledger</button></div><table><thead><tr><th>MATERIAL</th><th>ON HAND</th><th>LAST RATE</th></tr></thead><tbody>${mat}</tbody></table></div>`}
async function buyFlour(){
 const qty=document.querySelector('#purchaseQty').value,unit_price_rupees=document.querySelector('#purchaseRate').value;
 if(!Number.isFinite(Number(qty))||Number(qty)<=0||rupeesToPaise(unit_price_rupees)<=0){notify('Enter a positive quantity and purchase rate');return}
 try{const d=await api('/purchases/flour','POST',{qty,unit_price_rupees});notify(`Purchase recorded · flour now ${d.flour_stock} kg`);render()}catch(e){notify(e.message)}
}
async function saveRun(){
 const v={
  flour:document.querySelector('#flour').value,oil:document.querySelector('#oil').value,spice:document.querySelector('#spice').value,
  actual_output:Number(document.querySelector('#output').value),damaged_pouches:Number(document.querySelector('#damaged').value),cartons_used:Number(document.querySelector('#cartons').value),
  labour_rupees:document.querySelector('#labour').value,utilities_rupees:document.querySelector('#utilities').value
 };
 if([v.flour,v.oil,v.spice,v.labour_rupees,v.utilities_rupees].some(value=>value===''||!Number.isFinite(Number(value))||Number(value)<0)||[v.actual_output,v.damaged_pouches,v.cartons_used].some(value=>!Number.isInteger(value)||value<0)){notify('Production values must be valid non-negative numbers');return}
 try{const d=await api('/production/run','POST',v);notify(`Run posted · ${money(d.cost_per_packet_paise)} cost per packet`);render()}catch(e){notify(e.message)}
}
async function ordersPage(){
 const data=await api('/orders'),admin=['admin','owner'].includes(role());
 const emptyRows=admin
  ?`<tr><td colspan="11"><div class="empty-state"><div><b>No orders in the factory queue</b><p>Create an order from this workspace to start the workflow. Your other factory modules will remain available.</p></div><button class="btn" type="button" onclick="setPage('New Order')">Create an order</button></div></td></tr>`
  :'<tr><td colspan="11" class="empty">No orders yet. Use New order to create your first customer order.</td></tr>';
 const rows=data.map(o=>{
  const due=o.outstanding_paise||0;
  const collection=o.invoice_no?`${money(o.paid_paise)} paid · ${money(due)} due`:'—';
  const actions=admin&&o.status==='submitted'
   ?`<div class="order-review"><label>Qty <input id="order-qty-${o.id}" type="number" min="1" step="1" value="${o.lines[0].quantity}"></label><label>Price / packet (₹) <input id="order-price-${o.id}" type="number" min="0.01" step="0.01" value="${(o.lines[0].unit_price_paise/100).toFixed(2)}"></label><div class="actions"><button class="btn soft" type="button" onclick="decide(${o.id},true)">Approve</button><button class="btn warn" type="button" onclick="decide(${o.id},false)">Reject</button></div></div>`
   :admin&&o.status==='approved'
    ?`<button class="btn" type="button" onclick="dispatch(${o.id})">Dispatch</button>`
    :o.invoice_no
     ?`<div class="actions"><button class="btn secondary" type="button" onclick="invoice(${o.id})">Invoice</button>${admin&&due>0?`<button class="btn soft" type="button" onclick="openPayment(${o.id},${due})">Record payment</button>`:''}</div>`
     :status(o.status);
  const stockCheck=o.status==='submitted'?`<span class="${o.stock_shortage?'pill red':'pill'}">${o.stock_available} available${o.stock_shortage?` · ${o.stock_shortage} short`:''}</span>`:'—';
  return `<tr><td><b>#${o.id}</b></td><td><b>${o.customer}</b></td><td>${o.state}</td><td>${labels[o.salesperson]||o.salesperson}</td><td>Murukku 200 g</td><td>${o.lines[0].quantity}</td><td>${money(o.subtotal_paise)}</td><td>${money(o.gst_paise)} ${o.state==='Tamil Nadu'?'CGST + SGST':'IGST'}</td><td>${stockCheck}</td><td>${collection}</td><td>${actions}</td></tr>`;
 }).join('')||emptyRows;
 return `<div class="card"><div class="section-head"><div><h2>${role()==='salesman'?'Your orders':'Order queue'}</h2><p>${role()==='salesman'?'Track customer orders and fulfilment status':'Review or adjust quantities and prices, see available stock, invoice, dispatch, and record collections'}</p></div>${role()==='salesman'?'<button class="btn" type="button" onclick="setPage(\'New Order\')">＋ New order</button>':''}</div><div class="table-wrap"><table><thead><tr><th>ORDER</th><th>CUSTOMER</th><th>STATE</th><th>SALESPERSON</th><th>ITEM</th><th>QTY</th><th>TAXABLE</th><th>GST</th><th>STOCK CHECK</th><th>PAID / DUE</th><th>STATUS / ACTION</th></tr></thead><tbody>${rows}</tbody></table></div><div class="notice">Approval reserves finished-goods stock. Collections can be recorded as full or partial payments against dispatched invoices.</div></div>`;
}
async function decide(id,approved){const payload={approved};if(approved){const quantity=Number(document.querySelector(`#order-qty-${id}`).value),unit_price_paise=rupeesToPaise(document.querySelector(`#order-price-${id}`).value);if(!Number.isInteger(quantity)||quantity<1||!Number.isInteger(unit_price_paise)||unit_price_paise<=0){notify('Enter a positive quantity and price with up to two decimals');return}payload.quantity=quantity;payload.unit_price_paise=unit_price_paise}try{let d=await api(`/orders/${id}/decision`,'POST',payload);notify(approved?`Approved · ${d.stock} packets available`:'Order rejected');render()}catch(e){notify(e.message)}}
async function dispatch(id){try{let d=await api(`/orders/${id}/dispatch`,'POST',{});notify(`Dispatched · invoice ${d.invoice_no}`);render()}catch(e){notify(e.message)}}
function invoice(id){window.open(`/api/orders/${id}/invoice.pdf`,'_blank')}
function openPayment(id,outstanding){
 paymentOrderId=id;paymentOutstandingPaise=outstanding;
 document.querySelector('#paymentContext').textContent=`Order #${id} · outstanding balance ${money(outstanding)}`;
 const amount=document.querySelector('#paymentAmount');
 amount.value=(outstanding/100).toFixed(2);amount.max=(outstanding/100).toFixed(2);
 document.querySelector('#paymentDialog').classList.remove('hidden');
 amount.focus();
}
function closePayment(){document.querySelector('#paymentDialog').classList.add('hidden');paymentOrderId=null;paymentOutstandingPaise=0}
async function recordPayment(){
 const amount=document.querySelector('#paymentAmount').value,amountPaise=rupeesToPaise(amount);
 if(!paymentOrderId||!Number.isInteger(amountPaise)||amountPaise<=0){notify('Enter a payment greater than ₹0.00 with up to two decimals');return}
 if(amountPaise>paymentOutstandingPaise){notify('Payment cannot exceed the outstanding balance');return}
 try{
  await api(`/orders/${paymentOrderId}/payments`,'POST',{amount_rupees:amount});
  closePayment();notify('Collection recorded successfully');render();
 }catch(e){notify(e.message)}
}
async function newOrderPage(){let m=await api('/masters'),customers=m.customers.filter(x=>role()!=='salesman'||x.salesperson===user);if(!customers.length)return `<div class="card"><h2>Customer route not assigned</h2><p class="muted">Ask an Admin or Owner to assign customers to your Sales account in Users before submitting orders.</p></div>`;return `<div class="grid two"><div class="card"><div class="section-head"><div><h2>New customer order</h2><p>Send the order directly to the factory</p></div></div><div class="field"><label>Customer</label><select id="customer">${customers.map(x=>`<option value="${x.id}">${x.name} · ${x.state}</option>`).join('')}</select></div><div class="field"><label>Product</label><input value="Murukku 200 g · ₹50.00 / packet · GST 5%" disabled></div><div class="form-row"><div class="field"><label>Quantity (packets)</label><input id="qty" type="number" value="150" min="1"></div><button class="btn" onclick="placeOrder()">Submit order</button></div><div class="notice">Orders are saved locally and queue for factory review. If offline, this demo lets you continue in this browser; sync-on-reconnect is a documented extension point.</div></div><div class="card"><div class="section-head"><div><h2>Order preview</h2><p>Price list · GST calculated automatically</p></div></div><div class="activity"><div class="activity-row"><div class="activity-dot">₹</div><div><b>Murukku 200 g · ₹50.00</b><small>Taxable value is quantity × price list rate</small></div></div><div class="activity-row"><div class="activity-dot">%</div><div><b>GST at 5%</b><small>Tamil Nadu: split CGST + SGST · other states: IGST</small></div></div><div class="activity-row"><div class="activity-dot">▦</div><div><b>Stock verified by admin</b><small>Invoice only after available-stock check</small></div></div></div></div></div>`}
async function placeOrder(){
 const payload={customer_id:Number(document.querySelector('#customer').value),quantity:Number(document.querySelector('#qty').value)};
 if(!Number.isInteger(payload.quantity)||payload.quantity<1){notify('Order quantity must be at least one packet');return}
 try{const d=await api('/orders','POST',payload);notify(`Order #${d.id} submitted · ${d.shortage?`short ${d.shortage}`:'stock check ready'}`);setPage('My Orders')}
 catch(e){if(!navigator.onLine||e instanceof TypeError){const q=JSON.parse(localStorage.getItem('oa-queue')||'[]');q.push({...payload,user,queued_at:new Date().toISOString()});localStorage.setItem('oa-queue',JSON.stringify(q));notify('Saved offline · will send when connection returns');setPage('My Orders')}else notify(e.message)}
}
async function syncQueue(){if(!navigator.onLine||!user)return;let q=JSON.parse(localStorage.getItem('oa-queue')||'[]');if(!q.length)return;let left=q.filter(item=>item.user!==user),ready=q.filter(item=>item.user===user);for(const item of ready){try{await fetch('/api/orders',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({customer_id:item.customer_id,quantity:item.quantity})}).then(r=>{if(!r.ok)throw Error()})}catch{left.push(item)}}localStorage.setItem('oa-queue',JSON.stringify(left));if(ready.length>left.filter(item=>item.user===user).length){notify(`${ready.length-left.filter(item=>item.user===user).length} offline order(s) synced`);render()}}
window.addEventListener('online',syncQueue);window.addEventListener('load',syncQueue);
async function inventoryPage(){let s=await api('/stock');return `<div class="card"><div class="section-head"><div><h2>Stock summary</h2><p>Opening balance + receipts − issues and dispatches = closing balance</p></div><div class="actions"><a href="/api/ledger.csv" class="btn secondary" target="_blank">Export ledger CSV</a></div></div><div class="grid two"><div><h3 style="font:700 12px Manrope">Raw & packaging materials</h3><table><thead><tr><th>ITEM</th><th>TYPE</th><th>UNIT</th><th>OPENING</th><th>CLOSING</th><th>RATE</th></tr></thead><tbody>${s.materials.map(x=>`<tr><td><b>${x.name}</b></td><td>${x.category}</td><td>${x.unit}</td><td>${x.opening_qty}</td><td><b>${x.closing}</b></td><td>${money(x.rate_paise)}</td></tr>`).join('')}</tbody></table></div><div><h3 style="font:700 12px Manrope">Finished goods</h3><table><thead><tr><th>PRODUCT</th><th>PACK</th><th>OPENING</th><th>CLOSING</th></tr></thead><tbody>${s.products.map(x=>`<tr><td><b>${x.name}</b></td><td>${x.pack_g} g</td><td>${x.opening_qty}</td><td><b>${x.closing}</b></td></tr>`).join('')}</tbody></table><div class="notice">Each movement records its source document. The balances above are calculated from the ledger.</div></div></div></div><div class="card" style="margin-top:15px"><div class="section-head"><div><h2>Movement ledger</h2><p>Trace each receipt, production issue and dispatch</p></div></div><div class="table-wrap"><table><thead><tr><th>DATE</th><th>ITEM TYPE</th><th>ITEM ID</th><th>QUANTITY</th><th>SOURCE</th><th>DOCUMENT</th><th>NOTE</th></tr></thead><tbody>${s.ledger.map(x=>`<tr><td>${x.created_at}</td><td>${x.item_type}</td><td>${x.item_id}</td><td>${x.qty>0?'+':''}${x.qty}</td><td>${x.source_type}</td><td>${x.source_id}</td><td>${x.note}</td></tr>`).join('')||'<tr><td colspan="7" class="empty">Movements appear here as transactions are posted.</td></tr>'}</tbody></table></div></div>`}
async function reportsPage(){
 const params=new URLSearchParams();
 if(reportStart)params.set('start_date',reportStart);
 if(reportEnd)params.set('end_date',reportEnd);
 const query=params.toString(),d=await api(`/reports${query?`?${query}`:''}`),s=d.stock,exportQuery=query?`?${query}`:'';
 const ageingRows=d.ageing.map(x=>`<tr><td>${x.customer}</td><td>${money(x.current_paise)}</td><td>${money(x['1_30_days_paise'])}</td><td>${money(x['31_60_days_paise'])}</td><td>${money(x['61_plus_days_paise'])}</td><td><b>${money(x.total_paise)}</b></td></tr>`).join('')||'<tr><td colspan="6" class="empty">No outstanding invoices for this period.</td></tr>';
 return `<div class="section-head"><div><h2>Audit reports</h2><p>Sales register, GST summary, stock position, production variance and receivables</p></div><div class="actions"><a class="btn secondary" target="_blank" href="/api/reports.csv${exportQuery}">Export sales CSV</a><a class="btn secondary" target="_blank" href="/api/reports.pdf${exportQuery}">Export report PDF</a><a class="btn secondary" target="_blank" href="/api/ledger.csv">Export ledger CSV</a></div></div>
 <form class="report-filters" onsubmit="applyReportRange(event)"><label>From <input id="reportStart" type="date" value="${reportStart}"></label><label>To <input id="reportEnd" type="date" value="${reportEnd}"></label><button class="btn" type="submit">Apply range</button></form>
 <div class="grid stats">${card('TAXABLE SALES',money(d.gst.taxable_paise),'Invoices in selected period')}${card('OUTPUT GST',money(d.gst.gst_paise),'GSTR-1 / 3B summary basis')}${card('FINISHED STOCK',s.products[0].closing+' packets','Current Murukku 200 g stock')}${card('OUTSTANDING',money(d.sales.reduce((a,x)=>a+x.outstanding_paise,0)),'Selected invoices, as of period end')}</div>
 <div class="grid two"><div class="card"><div class="section-head"><div><h2>Sales & GST register</h2><p>Taxable value, outward tax and collection balance</p></div></div><div class="table-wrap"><table><thead><tr><th>INVOICE</th><th>DATE</th><th>CUSTOMER</th><th>STATUS</th><th>TAXABLE</th><th>GST</th><th>PAID</th><th>DUE</th></tr></thead><tbody>${d.sales.map(x=>`<tr><td>${x.invoice}</td><td>${x.invoice_date}</td><td>${x.customer}<small style="display:block;color:#88958f">${x.state}</small></td><td>${status(x.status)}</td><td>${money(x.taxable_paise)}</td><td>${money(x.gst_paise)}</td><td>${money(x.paid_paise)}</td><td><b>${money(x.outstanding_paise)}</b></td></tr>`).join('')||'<tr><td colspan="8" class="empty">No invoiced sales in this date range.</td></tr>'}</tbody></table></div></div>
 <div class="card"><div class="section-head"><div><h2>Stock & receivables</h2><p>Stock is current; ageing is calculated as of the selected end date</p></div></div><table><thead><tr><th>ITEM</th><th>ON HAND</th><th>UNIT</th></tr></thead><tbody>${s.materials.map(x=>`<tr><td>${x.name}</td><td>${x.closing}</td><td>${x.unit}</td></tr>`).join('')}${s.products.map(x=>`<tr><td>${x.name}</td><td>${x.closing}</td><td>packets</td></tr>`).join('')}</tbody></table>
 <h3>Receivables ageing</h3><div class="table-wrap"><table><thead><tr><th>CUSTOMER</th><th>CURRENT</th><th>1–30</th><th>31–60</th><th>61+</th><th>TOTAL</th></tr></thead><tbody>${ageingRows}</tbody></table></div>${d.production?`<div class="notice warning">Latest run: yield variance ${d.production.yield_variance_pct}%; cost per packet ${money(d.production.cost_per_packet_paise)}.</div>`:''}<p class="muted" style="font-size:10px">Purchase register and supplier management remain documented gaps.</p></div></div>`;
}
function applyReportRange(event){event.preventDefault();const start=document.querySelector('#reportStart').value,end=document.querySelector('#reportEnd').value;if(start&&end&&start>end){notify('Start date must not be after end date');return}reportStart=start;reportEnd=end;render()}
async function customersPage(){let m=await api('/masters'),o=await api('/orders');return `<div class="card"><div class="section-head"><div><h2>Customer accounts</h2><p>Assigned route customers and order history</p></div></div><div class="grid two">${m.customers.filter(c=>role()!=='salesman'||c.salesperson===user).map(c=>{let list=o.filter(x=>x.customer_id===c.id);return `<div class="card"><div class="section-head"><div><h2>${c.name}</h2><p>${c.state} · GSTIN ${c.gstin}</p></div><span class="pill">${escapeHtml(labels[c.salesperson]||c.salesperson||'Unassigned')}</span></div><div class="metric">${list.length} <span class="muted" style="font-size:11px">orders</span></div><button class="btn soft" style="margin-top:14px" onclick="setPage('New Order')">Create order →</button></div>`}).join('')}</div></div>`}
async function usersPage(){
 const data=await api('/users');
 const roleLabels={salesman:'Sales',production:'Production',auditor:'Auditor',admin:'Administrator',owner:'Owner'};
 const accountRows=data.users.map(account=>{
  const route=account.role==='salesman'?`<div class="route-assignment"><select id="route-${escapeHtml(account.user_id)}" multiple aria-label="Customer route for ${escapeHtml(account.user_id)}">${data.customers.map(customer=>`<option value="${customer.id}" ${customer.salesperson===account.user_id?'selected':''}>${escapeHtml(customer.name)}${customer.salesperson&&customer.salesperson!==account.user_id?' · assigned to '+escapeHtml(customer.salesperson):''}</option>`).join('')}</select><button class="btn secondary" type="button" onclick="assignCustomers('${escapeHtml(account.user_id)}')">Save route</button></div>`:'—';
  return `<tr><td><b>${escapeHtml(account.display)}</b></td><td>${escapeHtml(account.user_id)}</td><td>${roleLabels[account.role]||escapeHtml(account.role)}</td><td><span class="pill">${account.is_demo?'Demo':'Account'}</span></td><td>${escapeHtml(account.created_at)}</td><td>${route}</td></tr>`;
 }).join('');
 return `<div class="grid two"><div class="card"><div class="section-head"><div><h2>Create a team account</h2><p>Admin-created accounts can be Sales, Production, or Auditor.</p></div></div><form onsubmit="createUser(event)"><div class="field"><label for="newUserDisplay">Display name</label><input id="newUserDisplay" maxlength="80" required></div><div class="field"><label for="newUsername">Username</label><input id="newUsername" minlength="3" maxlength="30" pattern="[A-Za-z0-9][A-Za-z0-9._-]{2,29}" autocomplete="off" required></div><div class="field"><label for="newUserPassword">Password (12–128 characters)</label><input id="newUserPassword" type="password" minlength="12" maxlength="128" autocomplete="new-password" required></div><div class="field"><label for="newUserRole">Role</label><select id="newUserRole"><option value="salesman">Sales</option><option value="production">Production</option><option value="auditor">Auditor</option></select></div><button class="btn" type="submit">Create account</button></form></div><div class="card"><div class="section-head"><div><h2>Accounts and Sales routes</h2><p>Assign customers to a Sales account before it can place orders.</p></div></div><div class="table-wrap"><table><thead><tr><th>NAME</th><th>USERNAME</th><th>ROLE</th><th>TYPE</th><th>CREATED</th><th>CUSTOMER ROUTE</th></tr></thead><tbody>${accountRows||'<tr><td colspan="6" class="empty">No accounts found.</td></tr>'}</tbody></table></div></div></div>`;
}
async function createUser(event){
 event.preventDefault();
 const payload={display_name:document.querySelector('#newUserDisplay').value,username:document.querySelector('#newUsername').value,password:document.querySelector('#newUserPassword').value,role:document.querySelector('#newUserRole').value};
 try{const account=await api('/users','POST',payload);notify(`Created ${account.display} account`);event.currentTarget.reset();render()}catch(e){notify(e.message)}
}
async function assignCustomers(username){
 const select=document.getElementById(`route-${username}`),customer_ids=Array.from(select.selectedOptions).map(option=>Number(option.value));
 try{await api(`/users/${encodeURIComponent(username)}/customers`,'PUT',{customer_ids});notify('Customer route updated');render()}catch(e){notify(e.message)}
}
async function resetDemo(){if(!confirm('Reset all transactions to the original benchmark opening balances?'))return;try{await api('/reset','POST',{});notify('Benchmark reset to opening data');setPage('Overview')}catch(e){notify(e.message)}}
function toggleSwitch(show){document.querySelector('#switcher').classList.toggle('hidden',!show)}
function showLogin(message='',username='',success=false){const screen=document.querySelector('#loginScreen'),error=document.querySelector('#loginError');screen.classList.remove('hidden');document.querySelector('#loginPanel').hidden=false;document.querySelector('#registerPanel').hidden=true;screen.setAttribute('aria-labelledby','loginTitle');error.textContent=message;error.classList.toggle('login-success',success);document.querySelector('#loginUser').value=username||document.querySelector('#loginUser').value;document.querySelector('#loginPassword').value='';setTimeout(()=>document.querySelector('#loginUser').focus(),0)}
function showRegistration(){const screen=document.querySelector('#loginScreen');screen.classList.remove('hidden');document.querySelector('#loginPanel').hidden=true;document.querySelector('#registerPanel').hidden=false;screen.setAttribute('aria-labelledby','registerTitle');document.querySelector('#registerError').textContent='';document.querySelector('#registerPassword').value='';document.querySelector('#registerConfirm').value='';setTimeout(()=>document.querySelector('#registerDisplay').focus(),0)}
async function registerAccount(event){event.preventDefault();const username=document.querySelector('#registerUser').value.trim().toLowerCase(),display_name=document.querySelector('#registerDisplay').value.trim(),password=document.querySelector('#registerPassword').value,password_confirm=document.querySelector('#registerConfirm').value,error=document.querySelector('#registerError');if(password!==password_confirm){error.textContent='Passwords do not match';return}try{const account=await api('/register','POST',{username,display_name,password});document.querySelector('#registerPassword').value='';document.querySelector('#registerConfirm').value='';showLogin(account.message,account.user,true)}catch(e){error.textContent=e.message}}
async function login(event){event.preventDefault();const username=document.querySelector('#loginUser').value.trim().toLowerCase(),password=document.querySelector('#loginPassword').value;try{const account=await api('/login','POST',{username,password});user=account.user;userRole=account.role;userDisplay=account.display;userIsDemo=account.is_demo;page='Overview';document.querySelector('#loginScreen').classList.add('hidden');document.querySelector('#loginPassword').value='';render();syncQueue()}catch(e){const error=document.querySelector('#loginError');error.classList.remove('login-success');error.textContent=e.message;document.querySelector('#loginPassword').focus()}}
async function initialize(){try{const account=await api('/me');user=account.user;userRole=account.role;userDisplay=account.display;userIsDemo=account.is_demo;document.querySelector('#loginScreen').classList.add('hidden');render()}catch(e){showLogin('Sign in or create a Sales account to continue')}}
function openRoleSwitcher(){const options=userIsDemo?users.filter(u=>u!==user).map(u=>`<button type="button" class="role-option" onclick="switchRole('${u}')"><b>${labels[u]}</b><small>${u==='sales-a'?'Retailer A route':u==='sales-b'?'Distributor B route':u==='admin'?'Order approval and billing':u==='production'?'Materials and batch production':u==='auditor'?'Read-only reports':'Owner dashboard'}</small></button>`).join(''):'';document.querySelector('#roleOptions').innerHTML=options+`<button type="button" class="role-option" onclick="switchRole('')"><b>Sign out</b><small>End this session</small></button>`;toggleSwitch(true)}
document.querySelector('#roleSwitch').onclick=openRoleSwitcher;
async function switchRole(nextUser){const previousUser=user;toggleSwitch(false);try{await api('/logout','POST',{})}catch(e){if(e.status!==401){notify(e.message);return}}user=null;userRole=null;userDisplay=null;userIsDemo=false;showLogin(nextUser?`Sign in as ${labels[nextUser]}`:'Signed out',nextUser||previousUser)}
document.querySelector('#paymentDialog').addEventListener('click',event=>{if(event.target===event.currentTarget)closePayment()});
document.addEventListener('keydown',event=>{if(event.key==='Escape'){closePayment();toggleSwitch(false)}});
initialize();
