"""Regression tests for the Daily Cash & Bank Reconciliation board and the
Financial Tracking Filter Matrix (reference layouts), including the
lock -> next-day-opening carry-forward behaviour.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

ADMIN = {"username": "Admin", "password": "Admin@fbm12345"}


def _login(client):
    return client.post("/login", data=dict(ADMIN), follow_redirects=True)


def _mk_account(db, Account, name, category, opening):
    acc = Account(
        name=name,
        type="CASH" if category == "cash" else "BANK",
        account_type="company",
        category=category,
        balance=opening,
        opening_balance=opening,
        opening_balance_date=datetime(2026, 1, 1),
        is_active=True,
    )
    db.session.add(acc)
    db.session.commit()
    return acc


def _record(direction, amount, account, day, dest=None):
    from app.services.cash_flow_svc import save_manual_cash_flow_entry
    entry, created = save_manual_cash_flow_entry(
        direction=direction,
        amount=amount,
        account_id=account.id,
        destination_account_id=dest.id if dest else None,
        category_name="SALE" if direction == "in" else ("TRANSFER" if direction == "transfer" else "EXPENSE"),
        party_name="TEST PARTY",
        party_type="person",
        date_posted=datetime(day.year, day.month, day.day, 12, 0),
        create_missing=True,
    )
    assert created
    return entry


def test_reconciliation_page_renders(app, client):
    from models import db, Account
    with app.app_context():
        _mk_account(db, Account, "FBM CASH IN HAND", "cash", 1000.0)
    _login(client)
    rv = client.get("/daily_reconciliation")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "Daily Cash &amp; Bank Reconciliation" in body
    assert "OPEN FOR RECONCILIATION" in body
    assert "ACCOUNT POSITIONS FOR" in body
    assert "FBM CASH IN HAND" in body


def test_financial_tracker_renders_and_exports(app, client):
    from models import db, Account
    with app.app_context():
        acc = _mk_account(db, Account, "FBM CASH IN HAND", "cash", 500.0)
        _record("in", 200, acc, date.today())
        db.session.commit()
    _login(client)
    rv = client.get("/financial_tracker")
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert "FINANCIAL TRACKING FILTER MATRIX" in body
    assert "Matching Records" in body
    csv = client.get("/financial_tracker?export_csv=1")
    assert csv.status_code == 200
    assert "text/csv" in csv.headers["Content-Type"]


def test_lock_carries_counted_to_next_day_opening(app, client):
    from models import db, Account
    from app.services import cash_day_recon as recon

    with app.app_context():
        acc = _mk_account(db, Account, "FBM CASH IN HAND", "cash", 1000.0)
        today = date.today()
        _record("in", 500, acc, today)
        _record("out", 100, acc, today)
        db.session.commit()

    _login(client)
    day = date.today().isoformat()

    # expected closing = 1000 + 500 - 100 = 1400
    with app.app_context():
        pos = recon.account_positions_for_date(day)
        cash = [p for p in pos if p["account_name"].startswith("FBM CASH IN HAND")][0]
        assert cash["expected_closing"] == 1400.0
        acc_id = cash["account_id"]

    # Count 1,390 (Rs.10 short) then lock the day via the page route.
    rv = client.post("/daily_reconciliation", data={
        "action": "save_count", "day": day, "account_id": acc_id, "counted": "1390",
    }, follow_redirects=True)
    assert rv.status_code == 200
    rv = client.post("/daily_reconciliation", data={
        "action": "lock", "day": day, "note": "close",
    }, follow_redirects=True)
    assert rv.status_code == 200
    assert "locked" in rv.get_data(as_text=True).lower()

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    with app.app_context():
        lock = recon.get_day_lock(day)
        assert lock is not None
        assert lock.total_counted == 1390.0
        npos = recon.account_positions_for_date(tomorrow)
        ncash = [p for p in npos if p["account_name"].startswith("FBM CASH IN HAND")][0]
        # The locked counted closing (1,390) becomes tomorrow's opening.
        assert ncash["opening"] == 1390.0
        # clean up lock so other tests unaffected
        recon.unlock_day(day)
