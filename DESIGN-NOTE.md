# Design note: Order-to-Audit

## Data model and stock integrity

The system separates master data (`products`, `customers`, `materials`, `bom`) from source documents (`orders`, `production`, `payments`) and the stock subledger (`movements`). Authentication records are stored in `users` and `sessions`; existing `demo_users` rows are migrated at startup. Each movement carries a signed quantity and a source type/document ID. Materials and finished goods have seeded opening quantities; a current balance is calculated as opening plus the sum of ledger movements. No workflow overwrites an on-hand balance.

For the benchmark, the Murukku 200 g BOM expects 40 kg flour, 10 L oil, 1.2 kg spice mix, 200 pouches, and 10 cartons to yield 200 good packets. The run records actual material issues and output. Saving it creates negative material movements and a positive finished-goods movement in the same SQLite transaction. Actual pouch use is good output plus damaged pouches. Variance is (actual - planned) / planned and flags absolute values above 3%; yield uses the same formula against expected packets. Dispatch creates a negative finished-goods movement tied to the invoice/order.

## Cost and tax

Inventory valuation uses a moving weighted-average purchase rate. The flour benchmark rate becomes `(100 × ₹42 + 60 × ₹45) / 160 = ₹43.125/kg`, rounded half-up to ₹43.13/kg for the stored paisa rate. The 40 kg issue costs ₹1,725.20. Oil costs ₹1,470, spice ₹240, 194 pouches ₹485, and 9 cartons ₹135, for ₹4,055.20 material cost. ₹1,200 labour plus ₹600 gas/power are assigned directly to this run. Dividing ₹5,855.20 by 188 good packets gives ₹31.14 per packet, rounded to the nearest paisa. Currency values are stored as integer paisa.

The benchmark order is intra-state: 150 × ₹50 = ₹7,500 taxable; 5% GST is ₹375, split equally into ₹187.50 CGST and SGST. Orders outside Tamil Nadu use the same 5% as IGST in this exercise. Statutory rules and rates require verification before real-world use.

## Workflow and tradeoffs

The salesman submits a priced order. Admin approval can adjust quantity and price, checks unreserved finished-goods stock, and reserves stock until dispatch or rejection. Dispatch posts stock consumption and assigns a sequential financial-year invoice number. Payments reduce invoice outstanding. Reports filter invoices by issue date, calculate receivables ageing as of the selected period end, and export the sales register and stock ledger to CSV or an audit pack to PDF.

SQLite and a no-build frontend make the prototype easy to run and inspect in an interview. Existing demo users share a published password; public registration creates Sales-only accounts, while Admins and Owners can create Sales, Production, or Auditor accounts and assign customer routes. All accounts use salted PBKDF2 hashes, HTTP-only session cookies, and role checks on protected routes. A real deployment still needs registration throttling, email verification, password recovery, secure-cookie configuration, reviewed CSRF protections, PostgreSQL transaction controls, idempotent offline sync, credit notes, and statutory invoice numbering.
