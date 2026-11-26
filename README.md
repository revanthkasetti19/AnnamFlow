# Annam Foods | Order-to-Audit

A runnable prototype for the Winter Internship Application 2026 assignment. It connects mobile sales ordering, factory approval, GST invoicing, dispatch, recipe-based production, stock movements, costing, collections, and audit exports.

## Run it

### Docker (recommended)

Install Docker Desktop, open a terminal in this folder, and run:

```bash
docker compose up --build
```

Open <http://localhost:8000>. The benchmark master data is seeded automatically on first start. Use the reset button in the app to restore the original opening data and clear all transactions before another walkthrough. The Docker volume keeps the database when the container restarts.

### Python

Python 3.11+ is recommended.

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Open <http://localhost:8000>. The database is `backend/order_audit.db`; set `ORDER_AUDIT_DB` to choose another location. No accounting package or external service is needed.
For an HTTPS deployment, set `ORDER_AUDIT_COOKIE_SECURE=1` so the session cookie is sent only over TLS.

### Tests

From the project root, run `python -m unittest discover -s backend -p "test_*.py"`. The workflow tests use temporary SQLite files and do not alter the live demo database.

## Sign-in and accounts

Existing evaluation accounts share the demo password `AnnamDemo2026!`. New accounts use their own password; passwords are stored as salted PBKDF2 hashes and sessions use HTTP-only, 12-hour cookies.

| Role | Username | Main workflow |
|---|---|---|
| Factory admin | `admin` | Verify orders, adjust quantity/price, approve, invoice, dispatch, payments |
| Salesman A | `sales-a` | Submit and track Retailer A orders |
| Salesman B | `sales-b` | Submit Distributor B order and see shortage |
| Production supervisor | `production` | Record flour receipt, production run, and inventory |
| Auditor | `auditor` | Read-only reports and CSV exports |
| Owner | `owner` | Summary dashboard and all modules |

Sales roles see only their assigned customers and orders; raw-material/BOM details, the movement ledger, and production costing are restricted to factory and audit roles.

The sign-in screen supports public Sales registration. Admins and Owners can also create Sales, Production, or Auditor accounts from **Users**, and assign customers to Sales routes. Public sign-ups cannot choose a role and cannot place orders until an admin assigns customers. Admin/Owner accounts cannot be created through the user-management screen.

The shared demo credentials are for local evaluation, not production accounts. Public registration has no email verification or rate limiting, and the prototype has no password reset flow; a production deployment needs these protections, secure-cookie configuration, CSRF review, and organization-level authorization.

## Benchmark walkthrough

Reset the demo before recording. Then follow this order:

1. Select **Production** and record the flour purchase: 60 kg at ₹45/kg.
2. Post the run using the defaults: 40 kg flour, 10.5 L oil, 1.2 kg spice mix, 188 good packets, 6 damaged pouches, 9 cartons, ₹1,200 labour and ₹600 gas/power.
3. Confirm flour 120 kg, oil 19.5 L, spice 3.8 kg, pouches 306, cartons 21, and finished stock 238 packets. Yield is 188/200 (-6%); oil variance is +5%, both flagged.
4. Switch to **Salesman A** and submit 150 packets to Retailer A.
5. Sign in as **Factory Admin**, review the stock check, adjust quantity or price if needed, approve the order, then dispatch it. Download the invoice PDF. At the benchmark list price it is ₹7,500 taxable + ₹187.50 CGST + ₹187.50 SGST = ₹7,875. Finished stock becomes 88.
6. Switch to **Salesman B** and submit 120 packets to Distributor B. As admin, attempt approval: the API reports a shortage of 32 packets; it does not oversell stock. The order remains pending unless rejected or reduced.
7. In the admin order queue, use **Record payment** to collect ₹4,000 against Retailer A. The order list tracks paid and due amounts, and the API rejects payments above the remaining balance. Receivable is ₹3,875.
8. Show **Production** cost analysis and **Reports**; filter the reporting period, show receivables ageing, and export the sales CSV, stock ledger CSV, and audit PDF.

Offline order drafts are stored in browser local storage and synced when connectivity returns. This is intended for the single-browser demo; a production offline queue should use IndexedDB, server idempotency keys, and explicit conflict resolution.

## Benchmark calculations and assumptions

- **Stock:** opening quantity plus signed source-linked movement rows. Purchase receipts and production output are positive; production issues and dispatched sales are negative. The displayed balances are recomputed from this ledger.
- **Yield:** 40 kg flour represents one BOM batch with expected yield 200 packets. 188 good packets gives (188 - 200) / 200 = -6%.
- **Oil:** BOM standard is 10 L; actual 10.5 L is +5%. Tolerance is 3% absolute for consumption and yield.
- **Pouches:** 188 good pouches plus 6 damaged pouches are consumed, so closing is 500 - 194 = 306. Cartons close at 30 - 9 = 21.
- **Costing:** moving weighted-average valuation for raw materials and packaging, using integer paisa for currency and half-up rounding when the weighted rate falls between paisa. The flour rate after the benchmark purchase is (100 kg × ₹42 + 60 kg × ₹45) / 160 kg = ₹43.125/kg, rounded to ₹43.13/kg for the stored rate. The run consumes 40 kg at this rate, 10.5 L oil at ₹140/L, 1.2 kg spice at ₹200/kg, 194 pouches at ₹2.50, and 9 cartons at ₹15. Material cost is ₹4,055.20. Labour and gas/power total ₹1,800. Cost per good packet = ₹5,855.20 / 188 = **₹31.14** (rounded to nearest paisa).
- **Tax:** benchmark GST is 5%. The prototype splits it 2.5% CGST and 2.5% SGST for Tamil Nadu; for other states it calculates 5% IGST.
- **Invoice number:** sequential `FYyy-yy/NNNN` based on the server's current financial year. It is a demo sequence, not a statutory invoice numbering service.
- **Order shortage:** after 238 stock less 150 dispatched packets, 88 remain. The 120 packet distributor order therefore has a 32 packet shortage. It cannot be approved or dispatched at that quantity.

## Features against the assignment tiers

**Must have:** password sign-in with role checks, product/customer/material/BOM masters, mobile-responsive order entry, admin quantity/price review and stock reservations, GST invoice PDF, production run posting, planned-vs-actual variance, ledger-derived stock, sales and stock CSV exports.

**Should have:** flour purchase receipt, payments/outstanding and ageing, weighted-average run cost including overheads, GST report totals, variance flags, date-filtered CSV/PDF reports, and owner dashboard.

**Stretch:** browser offline order queue with online sync. Batch/expiry FEFO, supplier-backed purchase register, Tally export, and live government e-invoice integration are not implemented.

## Data model

SQLite tables: `products`, `customers`, `materials`, `bom`, `orders`, `production`, `payments`, `movements`, `audit`, `users`, and `sessions`. Existing `demo_users` rows are migrated to `users` at startup. `movements` is the stock subledger and carries item type/id, signed quantity, source type/id, note, and timestamp. Production runs save the actual issues and output, expected yield, overheads, and material valuation. Orders preserve the GST totals, status, line quantities, and invoice reference. Audit rows record who performed each meaningful posting.

## Known gaps

- The evaluation accounts share a published demo password. Use only for local evaluation; replace demo credentials, add login throttling, email verification and password recovery, configure secure cookies, and review CSRF and organization-level authorization before deployment.
- GST invoice PDF is a prototype representation, not a legal/tax opinion or a substitute for verifying current GST rules, HSN applicability, invoice series, and customer master data.
- Invoice cancellations with credit notes, returns, partial dispatch, supplier-backed purchase register, multiple product recipes, unit-conversion administration, and production rework need additional workflows.
- SQLite is appropriate for this single-process demo. A multi-user deployment should use PostgreSQL and transactions/locking around inventory reservations and document posting.
- No real customer or company data is included. All names and GSTIN-like values are fictional demo data.

## Stack

FastAPI provides a small typed HTTP API, and SQLite keeps the schema and ledger visible and easy to explain. The responsive HTML/CSS/JavaScript frontend keeps the field-sales path fast on a phone without a separate build tool; Docker Compose gives evaluators a one-command local run.
