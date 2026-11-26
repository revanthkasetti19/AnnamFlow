import os
import tempfile
import unittest
from pathlib import Path
from decimal import Decimal

from fastapi.testclient import TestClient

_test_database_root = tempfile.TemporaryDirectory()
os.environ['ORDER_AUDIT_DB'] = str(Path(_test_database_root.name) / 'import.db')

from backend import main


class OrderAuditWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.database = tempfile.TemporaryDirectory()
        main.DB = Path(self.database.name) / 'test.db'
        main.init()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        self.database.cleanup()

    def login(self, username):
        response = self.client.post('/api/login', json={
            'username': username,
            'password': main.DEMO_PASSWORD,
        })
        self.assertEqual(response.status_code, 200, response.text)

    def test_benchmark_posts_stock_invoice_collection_and_cost(self):
        self.login('production')
        purchase = self.client.post('/api/purchases/flour', json={
            'qty': '60',
            'unit_price_rupees': '45.00',
        })
        self.assertEqual(purchase.status_code, 200, purchase.text)

        run = self.client.post('/api/production/run', json={
            'flour': '40',
            'oil': '10.5',
            'spice': '1.2',
            'actual_output': 188,
            'damaged_pouches': 6,
            'cartons_used': 9,
            'labour_rupees': '1200.00',
            'utilities_rupees': '600.00',
        })
        self.assertEqual(run.status_code, 200, run.text)
        result = run.json()
        self.assertEqual(result['expected'], 200)
        self.assertEqual(result['actual'], 188)
        self.assertEqual(result['yield_variance_pct'], -6.0)
        self.assertTrue(result['yield_flagged'])
        self.assertEqual(result['consumption']['Cooking oil']['percent'], 5.0)
        self.assertTrue(result['consumption']['Cooking oil']['flagged'])
        self.assertEqual(result['material_cost_paise'], 405520)
        self.assertEqual(result['cost_per_packet_paise'], 3114)
        self.assertEqual(result['stock'], {
            'flour': 120.0,
            'oil': 19.5,
            'spice': 3.8,
            'pouches': 306.0,
            'cartons': 21.0,
            'finished_goods': 238,
        })

        self.login('sales-a')
        retailer_order = self.client.post('/api/orders', json={
            'customer_id': 1,
            'quantity': 150,
        })
        self.assertEqual(retailer_order.status_code, 200, retailer_order.text)
        order_id = retailer_order.json()['id']

        self.login('admin')
        approval = self.client.post(f'/api/orders/{order_id}/decision', json={
            'approved': True,
            'quantity': 150,
            'unit_price_paise': 5000,
        })
        self.assertEqual(approval.status_code, 200, approval.text)
        self.assertEqual(approval.json()['total_paise'], 787500)
        dispatch = self.client.post(f'/api/orders/{order_id}/dispatch', json={})
        self.assertEqual(dispatch.status_code, 200, dispatch.text)
        self.assertTrue(dispatch.json()['invoice_no'].startswith('FY'))
        self.assertEqual(dispatch.json()['stock'], 88)

        payment = self.client.post(
            f'/api/orders/{order_id}/payments',
            json={'amount_rupees': '4000.00'},
        )
        self.assertEqual(payment.status_code, 200, payment.text)
        reports = self.client.get('/api/reports').json()
        self.assertEqual(reports['sales'][0]['outstanding_paise'], 387500)
        self.assertEqual(reports['gst']['taxable_paise'], 750000)
        self.assertEqual(reports['gst']['gst_paise'], 37500)
        invoice_date = reports['sales'][0]['invoice_date']
        filtered = self.client.get('/api/reports', params={
            'start_date': invoice_date,
            'end_date': invoice_date,
        })
        self.assertEqual(len(filtered.json()['sales']), 1)
        self.assertTrue(
            self.client.get(f'/api/orders/{order_id}/invoice.pdf').content.startswith(b'%PDF')
        )
        self.assertTrue(self.client.get('/api/reports.pdf').content.startswith(b'%PDF'))

        self.login('sales-b')
        distributor_order = self.client.post('/api/orders', json={
            'customer_id': 2,
            'quantity': 120,
        })
        self.assertEqual(distributor_order.status_code, 200, distributor_order.text)
        shortage = self.client.post(
            f"/api/orders/{distributor_order.json()['id']}/decision",
            json={'approved': True},
        )
        self.assertEqual(shortage.status_code, 403)

        self.login('admin')
        shortage = self.client.post(
            f"/api/orders/{distributor_order.json()['id']}/decision",
            json={'approved': True},
        )
        self.assertEqual(shortage.status_code, 409)
        self.assertIn('32 packets short', shortage.json()['detail'])

    def test_login_and_role_boundaries(self):
        self.assertEqual(self.client.get('/api/me').status_code, 401)
        invalid_login = self.client.post('/api/login', json={
            'username': 'admin',
            'password': 'wrong',
        })
        self.assertEqual(invalid_login.status_code, 401)

        self.login('sales-a')
        self.assertEqual(self.client.get('/api/reports').status_code, 403)
        self.assertEqual(self.client.get('/api/orders').status_code, 200)
        masters = self.client.get('/api/masters').json()
        self.assertEqual([customer['id'] for customer in masters['customers']], [1])
        self.assertEqual(masters['materials'], [])
        self.assertEqual(masters['bom'], [])
        stock = self.client.get('/api/stock').json()
        self.assertEqual(stock['materials'], [])
        self.assertEqual(stock['ledger'], [])
        self.assertEqual(self.client.get('/api/production/latest').status_code, 403)

        self.login('sales-b')
        masters = self.client.get('/api/masters').json()
        self.assertEqual([customer['id'] for customer in masters['customers']], [2])

        self.login('production')
        summary = self.client.get('/api/summary').json()
        self.assertNotIn('outstanding_paise', summary)
        self.assertNotIn('orders_today', summary)
        self.assertEqual(self.client.get('/api/orders').status_code, 403)
        self.assertEqual(self.client.get('/api/reports').status_code, 403)

    def test_public_registration_is_sales_only_and_admin_assigns_customer_route(self):
        registration = self.client.post('/api/register', json={
            'username': 'new.sales',
            'display_name': 'New Sales User',
            'password': 'A-strong-password-2026',
            'role': 'owner',
        })
        self.assertEqual(registration.status_code, 201, registration.text)
        self.assertEqual(registration.json()['role'], 'salesman')
        self.assertEqual(self.client.get('/api/me').status_code, 401)
        self.assertEqual(self.client.post('/api/register', json={
            'username': 'new.sales',
            'display_name': 'Duplicate',
            'password': 'A-strong-password-2026',
        }).status_code, 409)

        sign_in = self.client.post('/api/login', json={
            'username': 'new.sales',
            'password': 'A-strong-password-2026',
        })
        self.assertEqual(sign_in.status_code, 200, sign_in.text)
        self.assertEqual(sign_in.json()['role'], 'salesman')
        self.assertFalse(sign_in.json()['is_demo'])
        self.assertEqual(self.client.get('/api/users').status_code, 403)
        self.assertEqual(self.client.post('/api/orders', json={
            'customer_id': 1,
            'quantity': 1,
        }).status_code, 403)

        self.client.post('/api/logout')
        self.login('admin')
        route = self.client.put('/api/users/new.sales/customers', json={
            'customer_ids': [1],
        })
        self.assertEqual(route.status_code, 200, route.text)
        accounts = self.client.get('/api/users').json()
        account = next(item for item in accounts['users'] if item['user_id'] == 'new.sales')
        self.assertEqual(account['role'], 'salesman')
        self.assertNotIn('password_hash', account)
        self.assertNotIn('password_salt', account)

        self.client.post('/api/logout')
        self.client.post('/api/login', json={
            'username': 'new.sales',
            'password': 'A-strong-password-2026',
        })
        self.assertEqual(
            [customer['id'] for customer in self.client.get('/api/masters').json()['customers']],
            [1],
        )
        order = self.client.post('/api/orders', json={'customer_id': 1, 'quantity': 1})
        self.assertEqual(order.status_code, 200, order.text)

    def test_admin_can_create_staff_accounts_but_not_privileged_admin_accounts(self):
        self.login('admin')
        created = self.client.post('/api/users', json={
            'username': 'audit.user',
            'display_name': 'Audit User',
            'password': 'Another-strong-password-2026',
            'role': 'auditor',
        })
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()['role'], 'auditor')
        forbidden_role = self.client.post('/api/users', json={
            'username': 'second.admin',
            'display_name': 'Second Admin',
            'password': 'Another-strong-password-2026',
            'role': 'owner',
        })
        self.assertEqual(forbidden_role.status_code, 400)
        self.client.post('/api/logout')
        self.client.post('/api/login', json={
            'username': 'audit.user',
            'password': 'Another-strong-password-2026',
        })
        self.assertEqual(self.client.get('/api/reports').status_code, 200)
        self.assertEqual(self.client.get('/api/users').status_code, 403)

    def test_legacy_demo_users_are_migrated(self):
        salt = b'0123456789abcdef'
        password = 'legacy-demo-password'
        password_hash = main.hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 210000).hex()
        with main.conn() as c:
            c.execute('CREATE TABLE demo_users(user_id TEXT PRIMARY KEY, role TEXT, display TEXT, password_salt TEXT, password_hash TEXT)')
            c.execute('INSERT INTO demo_users VALUES(?,?,?,?,?)', (
                'legacy-user', 'auditor', 'Legacy Auditor', salt.hex(), password_hash,
            ))

        main.init()
        sign_in = self.client.post('/api/login', json={
            'username': 'legacy-user',
            'password': password,
        })
        self.assertEqual(sign_in.status_code, 200, sign_in.text)
        self.assertEqual(sign_in.json()['role'], 'auditor')

    def test_reset_keeps_authenticated_session(self):
        self.login('admin')
        self.client.post('/api/orders', json={'customer_id': 1, 'quantity': 1})
        reset = self.client.post('/api/reset', json={})
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertEqual(self.client.get('/api/me').status_code, 200)
        self.assertEqual(self.client.get('/api/orders').json(), [])

    def test_admin_can_adjust_pending_order_and_approval_reserves_stock(self):
        self.login('sales-a')
        order = self.client.post('/api/orders', json={
            'customer_id': 1,
            'quantity': 2,
        }).json()

        self.login('admin')
        approval = self.client.post(f"/api/orders/{order['id']}/decision", json={
            'approved': True,
            'quantity': 3,
            'unit_price_paise': 5100,
        })
        self.assertEqual(approval.status_code, 200, approval.text)
        self.assertEqual(approval.json()['total_paise'], 16065)
        listed = self.client.get('/api/orders').json()
        self.assertEqual(listed[0]['lines'][0]['quantity'], 3)
        self.assertEqual(listed[0]['lines'][0]['unit_price_paise'], 5100)
        self.assertEqual(listed[0]['stock_available'], 47)

    def test_weighted_average_rounds_half_up(self):
        self.assertEqual(main.weighted_average_rate_paise(100, 4200, Decimal('60'), 4500), 4313)


if __name__ == '__main__':
    unittest.main()
