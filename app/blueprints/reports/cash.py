"""cash — split from reports.py."""
from ._common import *  # noqa

PARTY_TYPES = [
    ('person', 'Person'),
    ('outsider', 'Outsider / other party'),
    ('loan', 'Loan (person or outside lender)'),
    ('other', 'Other'),
]

DEFAULT_CF_CATEGORIES = [
    ('Loan Received', 'in', ['Personal loan', 'Bank loan']),
    ('Other Bank / Transfer In', 'in', []),
    ('Person', 'in', []),
    ('Outsider / Other Party', 'in', []),
    ('Other Income', 'in', []),
    ('Fuel', 'out', ['Petrol', 'Diesel', 'CNG']),
    ('Vehicle Repair', 'out', ['Parts', 'Labour', 'Workshop']),
    ('Food', 'out', []),
    ('Loan Paid', 'out', ['Personal loan', 'Bank loan']),
    ('Other Bank / Transfer Out', 'out', []),
    ('Person', 'out', []),
    ('Other Expense', 'out', []),
]


def _ensure_cash_flow_defaults():
    try:
        if CashFlowCategory.query.count() == 0:
            for i, (name, direction, subs) in enumerate(DEFAULT_CF_CATEGORIES):
                cat = CashFlowCategory(name=name, direction=direction, sort_order=i, is_active=True)
                db.session.add(cat)
                db.session.flush()
                for sub in subs:
                    db.session.add(CashFlowSubcategory(category_id=cat.id, name=sub, is_active=True))
            db.session.commit()
    except Exception:
        db.session.rollback()


def _find_or_create_cf_category(name, direction):
    name = (name or '').strip()
    if not name:
        return None
    existing = CashFlowCategory.query.filter(
        func.lower(CashFlowCategory.name) == name.lower(),
        CashFlowCategory.is_active == True
    ).first()
    if existing:
        return existing
    cat = CashFlowCategory(name=name, direction=direction if direction in ('in', 'out') else 'both', is_active=True)
    db.session.add(cat)
    db.session.flush()
    return cat


def _find_or_create_cf_subcategory(category, name):
    name = (name or '').strip()
    if not category or not name:
        return None
    existing = CashFlowSubcategory.query.filter(
        CashFlowSubcategory.category_id == category.id,
        func.lower(CashFlowSubcategory.name) == name.lower(),
        CashFlowSubcategory.is_active == True
    ).first()
    if existing:
        return existing
    sub = CashFlowSubcategory(category_id=category.id, name=name, is_active=True)
    db.session.add(sub)
    db.session.flush()
    return sub


def _find_or_create_cf_party(name, party_type):
    name = (name or '').strip()
    if not name:
        return None
    ptype = (party_type or 'other').strip().lower() or 'other'
    existing = CashFlowParty.query.filter(
        func.lower(CashFlowParty.name) == name.lower(),
        func.lower(func.coalesce(CashFlowParty.party_type, '')) == ptype,
        CashFlowParty.is_active == True
    ).first()
    if existing:
        return existing
    party = CashFlowParty(name=name, party_type=ptype, is_active=True)
    db.session.add(party)
    db.session.flush()
    return party


def _empty_row_meta():
    return {
        'category': '',
        'subcategory': '',
        'party_name': '',
        'party_type': '',
        'account_name': '',
        'entry_id': None,
    }


@bp.route('/cash_flow', methods=['GET', 'POST'])
@login_required
def cash_flow():
    _ensure_cash_flow_defaults()
    source = request.form if request.method == 'POST' else request.args
    fresh_start_dt = pk_today()
    fresh_start_date = fresh_start_dt.strftime('%Y-%m-%d')
    from_date = source.get('from_date', fresh_start_date)
    to_date = source.get('to_date', fresh_start_date)
    filter_type = source.get('filter_type', 'all')
    filter_origin = (source.get('origin') or 'all').strip().lower()
    filter_category = (source.get('category') or '').strip()
    filter_subcategory = (source.get('subcategory') or '').strip()
    filter_party_type = (source.get('party_type') or '').strip().lower()
    filter_party = (source.get('party') or '').strip()
    filter_account_id = source.get('account_id', type=int)
    filter_q = (source.get('q') or '').strip()
    opening_balance_input = source.get('opening_balance', '').strip()
    export_pdf = request.args.get('export_pdf', '')

    adjustment_date_input = to_date
    physical_cash_input = ''
    reconciliation_reason = ''
    action = ''
    if request.method == 'POST':
        adjustment_date_input = request.form.get('adjustment_date', to_date).strip() or to_date
        physical_cash_input = request.form.get('physical_cash_available', '').strip()
        reconciliation_reason = request.form.get('reconciliation_reason', '').strip()
        action = request.form.get('action', '').strip()

    if request.method == 'POST' and action == 'add_category':
        name = (request.form.get('new_category_name') or '').strip()
        direction = (request.form.get('new_category_direction') or 'both').strip().lower()
        if not name:
            flash('Category name is required.', 'danger')
        else:
            _find_or_create_cf_category(name, direction)
            db.session.commit()
            flash(f'Category “{name}” saved.', 'success')
        return redirect(url_for('cash_flow', from_date=from_date, to_date=to_date, filter_type=filter_type))

    if request.method == 'POST' and action == 'add_subcategory':
        cat_id = request.form.get('new_sub_category_id', type=int)
        name = (request.form.get('new_subcategory_name') or '').strip()
        cat = CashFlowCategory.query.get(cat_id) if cat_id else None
        if not cat or not name:
            flash('Pick a category and enter a sub-category name.', 'danger')
        else:
            _find_or_create_cf_subcategory(cat, name)
            db.session.commit()
            flash(f'Sub-category “{name}” added under {cat.name}.', 'success')
        return redirect(url_for('cash_flow', from_date=from_date, to_date=to_date, filter_type=filter_type))

    if request.method == 'POST' and action == 'add_party':
        name = (request.form.get('new_party_name') or '').strip()
        ptype = (request.form.get('new_party_type') or 'person').strip().lower()
        if not name:
            flash('Name is required.', 'danger')
        else:
            _find_or_create_cf_party(name, ptype)
            db.session.commit()
            flash(f'Party “{name}” saved.', 'success')
        return redirect(url_for('cash_flow', from_date=from_date, to_date=to_date, filter_type=filter_type))

    if request.method == 'POST' and action == 'delete_entry':
        entry_id = request.form.get('entry_id', type=int)
        entry = CashFlowEntry.query.get(entry_id) if entry_id else None
        if not entry:
            flash('Entry not found.', 'warning')
        else:
            if entry.account_tx_id:
                tx = AccountTransaction.query.get(entry.account_tx_id)
                if tx and not tx.is_void:
                    if tx.to_account_id:
                        a = Account.query.get(tx.to_account_id)
                        if a:
                            a.balance = float(a.balance or 0) - float(tx.amount or 0)
                    if tx.from_account_id:
                        a = Account.query.get(tx.from_account_id)
                        if a:
                            a.balance = float(a.balance or 0) + float(tx.amount or 0)
                    db.session.delete(tx)
            db.session.delete(entry)
            db.session.commit()
            audit_log(current_user, 'cash_flow.entry.delete', f'id={entry_id}')
            flash('Cash flow entry deleted and account balance corrected.', 'success')
        return redirect(url_for('cash_flow', from_date=from_date, to_date=to_date, filter_type=filter_type))

    if request.method == 'POST' and action == 'record_movement':
        direction = (request.form.get('direction') or '').strip().lower()
        amount = _money_round(request.form.get('amount', 0))
        account_id = request.form.get('cash_account_id', type=int)
        description = (request.form.get('description') or '').strip()
        note = (request.form.get('movement_note') or '').strip()
        date_raw = (request.form.get('movement_date') or '').strip()
        category_id = request.form.get('category_id', type=int)
        category_name = (request.form.get('category_name') or '').strip()
        subcategory_id = request.form.get('subcategory_id', type=int)
        subcategory_name = (request.form.get('subcategory_name') or '').strip()
        party_id = request.form.get('party_id', type=int)
        party_name = (request.form.get('party_name') or '').strip()
        party_type = (request.form.get('party_type') or 'other').strip().lower()
        try:
            posted = datetime.strptime(date_raw, '%Y-%m-%dT%H:%M') if date_raw else pk_now()
        except Exception:
            posted = pk_now()
        acc = Account.query.get(account_id) if account_id else None
        if acc and (acc.category or '').lower() not in ('cash', 'bank'):
            acc = None
        if amount <= 0:
            flash('Amount must be greater than zero.', 'danger')
        elif not acc or not acc.is_active:
            flash('Select a company cash/bank account from Accounts. New accounts cannot be created on Cash Flow.', 'danger')
        elif direction not in ('in', 'out'):
            flash('Choose Received or Spent.', 'danger')
        else:
            cat = CashFlowCategory.query.get(category_id) if category_id else None
            if not cat:
                cat = _find_or_create_cf_category(category_name, direction)
            sub = CashFlowSubcategory.query.get(subcategory_id) if subcategory_id else None
            if not sub:
                sub = _find_or_create_cf_subcategory(cat, subcategory_name)
            party = CashFlowParty.query.get(party_id) if party_id else None
            if not party:
                party = _find_or_create_cf_party(party_name, party_type)
            if party:
                party_name = party.name
                party_type = party.party_type or party_type
            marker = '[SRC:CashFlow]'
            label = description or (cat.name if cat else ('Cash received' if direction == 'in' else 'Cash spent'))
            if party_name:
                label = f'{label} — {party_name}'
            if direction == 'in':
                acc.balance = float(acc.balance or 0) + amount
                tx = AccountTransaction(
                    from_account_id=None, to_account_id=acc.id, amount=amount,
                    description=label, note=' '.join(x for x in [note, marker] if x).strip(),
                    transaction_type='Receipt', date_posted=posted,
                )
            else:
                if float(acc.balance or 0) < amount:
                    flash(f'Insufficient balance in {acc.name}.', 'danger')
                    return redirect(url_for('cash_flow', from_date=from_date, to_date=to_date, filter_type=filter_type))
                acc.balance = float(acc.balance or 0) - amount
                tx = AccountTransaction(
                    from_account_id=acc.id, to_account_id=None, amount=amount,
                    description=label, note=' '.join(x for x in [note, marker] if x).strip(),
                    transaction_type='Expense', date_posted=posted,
                )
            db.session.add(tx)
            db.session.flush()
            db.session.add(CashFlowEntry(
                direction=direction, amount=amount, account_id=acc.id,
                category_id=cat.id if cat else None,
                subcategory_id=sub.id if sub else None,
                party_id=party.id if party else None,
                party_name=party_name or None, party_type=party_type or None,
                description=description or label, note=note or None,
                date_posted=posted, created_by=_current_username(),
                account_tx_id=tx.id, is_void=False,
            ))
            db.session.commit()
            audit_log(current_user, 'cash_flow.record', f'dir={direction}, amount={amount}')
            flash(f'{"Received" if direction == "in" else "Spent"} Rs. {amount:,.0f} recorded.', 'success')
        return redirect(url_for('cash_flow', from_date=from_date, to_date=to_date, filter_type=filter_type))

    if request.method == 'POST' and action in ('set_opening_override', 'clear_opening_override', 'reset_fresh_start'):
        if action == 'reset_fresh_start':
            session['cash_flow_fresh_start_cutoff'] = {
                'date': fresh_start_date,
                'at': pk_now().strftime('%Y-%m-%d %H:%M:%S'),
            }
            session.pop('cash_flow_today_opening_override', None)
            flash('Cash Flow fresh-start view reset. Existing entries are hidden from this report and today opening is Rs. 0.', 'success')
            return redirect(url_for('cash_flow', from_date=fresh_start_date, to_date=fresh_start_date, filter_type='all'))
        if action == 'clear_opening_override':
            session.pop('cash_flow_today_opening_override', None)
            flash('Today cash flow opening override cleared. Opening is back to Rs. 0.', 'success')
        else:
            opening_override_amount = _money_round(request.form.get('today_opening_override', 0))
            session['cash_flow_today_opening_override'] = {
                'date': fresh_start_date,
                'amount': opening_override_amount,
            }
            flash(f'Today cash flow opening override set to Rs. {opening_override_amount:,.0f}. Source accounts were not changed.', 'success')
        return redirect(url_for('cash_flow', from_date=fresh_start_date, to_date=fresh_start_date, filter_type='all'))

    try:
        from_date_dt = datetime.strptime(from_date, '%Y-%m-%d').date()
    except Exception:
        from_date_dt = fresh_start_dt
    try:
        to_date_dt = datetime.strptime(to_date, '%Y-%m-%d').date()
    except Exception:
        to_date_dt = fresh_start_dt

    fresh_start_clamped = False
    if from_date_dt < fresh_start_dt:
        from_date_dt = fresh_start_dt
        from_date = fresh_start_date
        fresh_start_clamped = True
    if to_date_dt < from_date_dt:
        to_date_dt = from_date_dt
        to_date = from_date_dt.strftime('%Y-%m-%d')

    # Opening balance: user-entered OR authoritative carry-forward from prior physical cash reconciliation.
    today_opening_override = _cash_flow_today_opening_override(fresh_start_date)
    if opening_balance_input:
        try:
            opening_balance = float(opening_balance_input)
        except ValueError:
            opening_balance = 0.0
    elif from_date_dt == fresh_start_dt:
        opening_balance = today_opening_override if today_opening_override is not None else 0.0
    else:
        opening_balance = _automatic_cash_opening_balance(from_date_dt)

    # Build cash-in rows
    fresh_start_cutoff = _cash_flow_fresh_start_cutoff(fresh_start_date)
    hide_existing_today_entries = from_date_dt == fresh_start_dt
    cash_in_rows = []
    cash_method_clauses = [
        func.lower(func.trim(func.coalesce(Payment.method, ''))) == 'cash',
        func.lower(func.trim(func.coalesce(Payment.method, ''))) == 'cash sale',
    ]
    payment_query = Payment.query.filter(
        Payment.is_void == False,
        or_(*cash_method_clauses),
        func.date(Payment.date_posted) >= from_date,
        func.date(Payment.date_posted) <= to_date
    )
    if hide_existing_today_entries:
        payment_query = payment_query.filter(Payment.date_posted > fresh_start_cutoff)
    for p in payment_query.order_by(Payment.date_posted).all():
        cash_in_rows.append({
            'date': p.date_posted.date() if hasattr(p.date_posted, 'date') else p.date_posted,
            'sort_dt': p.date_posted,
            'reference': p.manual_bill_no or p.auto_bill_no or f'PAY-{p.id}',
            'description': f'Client Payment — {p.client_name or ""}',
            'cash_in': float(p.amount or 0),
            'cash_out': 0.0,
            'origin': 'derived',
            'origin_label': 'From Accounts · Client Payments',
            **_empty_row_meta(),
            'party_name': p.client_name or '',
            'party_type': 'client',
            'category': 'Client Payment',
        })

    sale_query = DirectSale.query.filter(
        DirectSale.is_void == False,
        or_(
            func.lower(func.trim(func.coalesce(DirectSale.category, ''))) == 'cash',
            func.lower(func.trim(func.coalesce(DirectSale.category, ''))) == 'cash sale',
            func.lower(func.trim(func.coalesce(DirectSale.payment_method, ''))) == 'cash',
            func.lower(func.trim(func.coalesce(DirectSale.payment_method, ''))) == 'cash sale',
        ),
        DirectSale.paid_amount > 0,
        func.date(DirectSale.date_posted) >= from_date,
        func.date(DirectSale.date_posted) <= to_date
    )
    if hide_existing_today_entries:
        sale_query = sale_query.filter(DirectSale.date_posted > fresh_start_cutoff)
    for s in sale_query.order_by(DirectSale.date_posted).all():
        cash_in_rows.append({
            'date': s.date_posted.date() if hasattr(s.date_posted, 'date') else s.date_posted,
            'sort_dt': s.date_posted,
            'reference': s.manual_bill_no or s.auto_bill_no or f'DS-{s.id}',
            'description': f'Cash Sale — {s.client_name or ""}',
            'cash_in': float(s.paid_amount or 0),
            'cash_out': 0.0,
            'origin': 'derived',
            'origin_label': 'From Sales',
            **_empty_row_meta(),
            'party_name': s.client_name or '',
            'party_type': 'client',
            'category': 'Cash Sale',
        })

    # Build cash-out rows
    cash_out_rows = []
    supplier_payment_query = SupplierPayment.query.filter(
        SupplierPayment.is_void == False,
        func.date(SupplierPayment.date_posted) >= from_date,
        func.date(SupplierPayment.date_posted) <= to_date
    )
    if hide_existing_today_entries:
        supplier_payment_query = supplier_payment_query.filter(SupplierPayment.date_posted > fresh_start_cutoff)
    for sp in supplier_payment_query.order_by(SupplierPayment.date_posted).all():
        supplier_name = sp.supplier.name if sp.supplier else ''
        cash_out_rows.append({
            'date': sp.date_posted.date() if hasattr(sp.date_posted, 'date') else sp.date_posted,
            'sort_dt': sp.date_posted,
            'reference': sp.manual_bill_no or sp.auto_bill_no or f'SUP-{sp.id}',
            'description': f'Supplier Payment — {supplier_name}',
            'cash_in': 0.0,
            'cash_out': float(sp.amount or 0),
            'origin': 'derived',
            'origin_label': 'From Accounts · Supplier Payments',
            **_empty_row_meta(),
            'party_name': supplier_name,
            'party_type': 'supplier',
            'category': 'Supplier Payment',
        })

    # Use the FBM drawer cash account as the source of truth for cash flow transfers.
    fbm_drawer_account = Account.query.filter(
        func.lower(func.trim(Account.name)) == 'fbm drawer cash'
    ).first()
    if not fbm_drawer_account:
        fbm_drawer_account = Account.query.filter(
            Account.name.ilike('%fbm drawer cash%')
        ).first()
    fbm_drawer_account_id = fbm_drawer_account.id if fbm_drawer_account else None

    # Include general expenses and FBM drawer transfers from AccountTransaction.
    account_tx_query = AccountTransaction.query.filter(
        AccountTransaction.is_void == False,
        AccountTransaction.transaction_type.in_(['Expense', 'Payment', 'Transfer', 'Receipt']),
        func.date(AccountTransaction.date_posted) >= from_date,
        func.date(AccountTransaction.date_posted) <= to_date
    )
    if hide_existing_today_entries:
        account_tx_query = account_tx_query.filter(AccountTransaction.date_posted > fresh_start_cutoff)
    def _tx_note(tx):
        return (tx.note or '')

    def _is_derived_account_tx(tx):
        n = _tx_note(tx).upper()
        # Source-document receipts/payments are rendered from their source
        # tables above.  Including these AccountTransaction mirrors would
        # show the same cash movement twice in Cash Flow.
        return any(marker in n for marker in (
            '[SRC:BOOKING:',
            '[SRC:DIRECTSALE:',
            '[SRC:PAYMENT:',
            '[SRC:SUPPLIERPAYMENT:',
            '[SRC:CLIENTREFUND:',
        ))

    for tx in account_tx_query.all():
        note_u = _tx_note(tx).upper()
        recorded = '[SRC:CASHFLOW]' in note_u
        origin = 'recorded' if recorded else 'derived'
        origin_label = 'Recorded on Cash Flow' if recorded else 'From Accounts'

        if _is_derived_account_tx(tx) or recorded:
            continue

        if tx.transaction_type == 'Transfer' and fbm_drawer_account_id is not None:
            if tx.to_account_id == fbm_drawer_account_id and tx.from_account_id != fbm_drawer_account_id:
                cash_in_rows.append({
                    'date': tx.date_posted.date() if hasattr(tx.date_posted, 'date') else tx.date_posted,
                    'sort_dt': tx.date_posted,
                    'reference': f'TX-{tx.id}',
                    'description': tx.description or 'Transfer to FBM DRAWER CASH',
                    'cash_in': float(tx.amount or 0),
                    'cash_out': 0.0,
                    'origin': origin,
                    'origin_label': origin_label,
                    **_empty_row_meta(),
                    'category': 'Transfer',
                })
                continue
            if tx.from_account_id == fbm_drawer_account_id and tx.to_account_id != fbm_drawer_account_id:
                cash_out_rows.append({
                    'date': tx.date_posted.date() if hasattr(tx.date_posted, 'date') else tx.date_posted,
                    'sort_dt': tx.date_posted,
                    'reference': f'TX-{tx.id}',
                    'description': tx.description or 'Transfer from FBM DRAWER CASH',
                    'cash_in': 0.0,
                    'cash_out': float(tx.amount or 0),
                    'origin': origin,
                    'origin_label': origin_label,
                    **_empty_row_meta(),
                    'category': 'Transfer',
                })
                continue

        if tx.transaction_type == 'Receipt' and tx.to_account_id is not None:
            acc = Account.query.get(tx.to_account_id)
            if acc and (acc.category or '').lower() in ('cash', 'bank'):
                cash_in_rows.append({
                    'date': tx.date_posted.date() if hasattr(tx.date_posted, 'date') else tx.date_posted,
                    'reference': f'TX-{tx.id}',
                    'description': tx.description or 'Cash received',
                    'cash_in': float(tx.amount or 0),
                    'cash_out': 0.0,
                    'origin': origin,
                    'origin_label': origin_label if recorded else 'From Accounts · Other receive',
                })
            continue

        if tx.transaction_type in ['Expense', 'Payment'] and tx.from_account_id is not None:
            acc = Account.query.get(tx.from_account_id)
            if acc and (acc.category or '').lower() in ('cash', 'bank'):
                cash_out_rows.append({
                    'date': tx.date_posted.date() if hasattr(tx.date_posted, 'date') else tx.date_posted,
                    'reference': f'TX-{tx.id}',
                    'description': tx.description or 'Expense',
                    'cash_in': 0.0,
                    'cash_out': float(tx.amount or 0),
                    'origin': origin,
                    'origin_label': origin_label if recorded else 'From Accounts · Expense',
                })

    recorded_query = CashFlowEntry.query.filter(
        CashFlowEntry.is_void == False,
        func.date(CashFlowEntry.date_posted) >= from_date,
        func.date(CashFlowEntry.date_posted) <= to_date,
    )
    if hide_existing_today_entries:
        recorded_query = recorded_query.filter(CashFlowEntry.date_posted > fresh_start_cutoff)
    for e in recorded_query.all():
        acc_name = e.account.name if e.account else ''
        cat_name = e.category.name if e.category else ''
        sub_name = e.subcategory.name if e.subcategory else ''
        row = {
            'date': e.date_posted.date() if hasattr(e.date_posted, 'date') else e.date_posted,
            'sort_dt': e.date_posted,
            'reference': f'CF-{e.id}',
            'description': e.description or cat_name or 'Cash movement',
            'cash_in': float(e.amount or 0) if e.direction == 'in' else 0.0,
            'cash_out': float(e.amount or 0) if e.direction == 'out' else 0.0,
            'origin': 'recorded',
            'origin_label': 'Recorded on Cash Flow',
            'category': cat_name,
            'subcategory': sub_name,
            'party_name': e.party_name or (e.party.name if e.party else ''),
            'party_type': e.party_type or (e.party.party_type if e.party else ''),
            'account_name': acc_name,
            'entry_id': e.id,
        }
        if e.direction == 'in':
            cash_in_rows.append(row)
        else:
            cash_out_rows.append(row)

    # Merge and sort
    all_rows = cash_in_rows + cash_out_rows
    def _sort_key(r):
        d = r.get('sort_dt') or r.get('date')
        if hasattr(d, 'timestamp'):
            return (d.timestamp(), r.get('reference') or '')
        try:
            return (datetime.combine(d, datetime.min.time()).timestamp(), r.get('reference') or '')
        except Exception:
            return (0, r.get('reference') or '')
    all_rows.sort(key=_sort_key)

    # Apply filter
    if filter_type == 'cash_in':
        display_rows = [r for r in all_rows if r['cash_in'] > 0]
    elif filter_type == 'cash_out':
        display_rows = [r for r in all_rows if r['cash_out'] > 0]
    else:
        display_rows = all_rows

    if filter_origin in ('derived', 'recorded'):
        display_rows = [r for r in display_rows if r.get('origin') == filter_origin]
    if filter_category:
        needle = filter_category.lower()
        display_rows = [r for r in display_rows if needle in (r.get('category') or '').lower()]
    if filter_subcategory:
        needle = filter_subcategory.lower()
        display_rows = [r for r in display_rows if needle in (r.get('subcategory') or '').lower()]
    if filter_party_type:
        display_rows = [r for r in display_rows if (r.get('party_type') or '').lower() == filter_party_type]
    if filter_party:
        needle = filter_party.lower()
        display_rows = [r for r in display_rows if needle in (r.get('party_name') or '').lower()]
    if filter_account_id:
        acc_obj = Account.query.get(filter_account_id)
        acc_name = (acc_obj.name if acc_obj else '').lower()
        display_rows = [r for r in display_rows if acc_name and acc_name in (r.get('account_name') or '').lower()]
    if filter_q:
        needle = filter_q.lower()
        display_rows = [r for r in display_rows if needle in ' '.join([
            str(r.get('description') or ''),
            str(r.get('party_name') or ''),
            str(r.get('category') or ''),
            str(r.get('subcategory') or ''),
            str(r.get('reference') or ''),
        ]).lower()]

    # Compute running balance
    running = opening_balance
    for r in display_rows:
        running += r['cash_in'] - r['cash_out']
        r['running_balance'] = running
    closing_balance = running

    total_cash_in = sum(r['cash_in'] for r in display_rows)
    total_cash_out = sum(r['cash_out'] for r in display_rows)

    try:
        adjustment_date_dt = datetime.strptime(adjustment_date_input, '%Y-%m-%d').date()
    except Exception:
        adjustment_date_dt = datetime.strptime(to_date, '%Y-%m-%d').date()

    adjustment_entry = CashFlowDifferenceAdjustment.query.filter_by(adjustment_date=adjustment_date_dt).first()
    if request.method == 'POST':
        if action == 'delete':
            if adjustment_entry:
                audit = CashFlowReconciliationAudit(
                    reconciliation_id=adjustment_entry.id,
                    adjustment_date=adjustment_entry.adjustment_date,
                    change_type='DELETE',
                    old_physical_cash=adjustment_entry.physical_cash_available,
                    old_difference=adjustment_entry.difference if adjustment_entry.difference is not None else adjustment_entry.amount,
                    old_reason=adjustment_entry.reason or adjustment_entry.note,
                    changed_by=_current_username(),
                    changed_at=pk_model_now(),
                )
                db.session.add(audit)
                adjustment_entry.physical_cash_available = None
                adjustment_entry.calculated_closing = None
                adjustment_entry.difference = None
                adjustment_entry.reason = None
                adjustment_entry.amount = 0
                adjustment_entry.note = 'Reconciliation removed; audit trail retained.'
                adjustment_entry.edited_by = _current_username()
                adjustment_entry.edited_date = pk_model_now()
                adjustment_entry.edit_count = (adjustment_entry.edit_count or 0) + 1
                db.session.commit()
                flash(f'Reconciliation removed for {adjustment_date_dt.strftime("%Y-%m-%d")}. Audit trail retained.', 'success')
        elif physical_cash_input == '':
            flash('Physical Cash Available is required. Difference is calculated by the system.', 'danger')
        else:
            physical_cash_available = _money_round(physical_cash_input)
            difference = _money_round(closing_balance - physical_cash_available)
            username = _current_username()
            if not adjustment_entry:
                adjustment_entry = CashFlowDifferenceAdjustment(
                    adjustment_date=adjustment_date_dt,
                    created_by=username,
                    created_at=pk_model_now(),
                    edit_count=0,
                )
                db.session.add(adjustment_entry)
                db.session.flush()
                change_type = 'CREATE'
                old_physical_cash = None
                old_difference = None
                old_reason = None
            else:
                change_type = 'EDIT' if adjustment_entry.physical_cash_available is not None else 'CREATE'
                old_physical_cash = adjustment_entry.physical_cash_available
                old_difference = adjustment_entry.difference if adjustment_entry.difference is not None else adjustment_entry.amount
                old_reason = adjustment_entry.reason or adjustment_entry.note
                adjustment_entry.old_physical_cash = old_physical_cash
                adjustment_entry.edited_by = username
                adjustment_entry.edited_date = pk_model_now()

            adjustment_entry.physical_cash_available = physical_cash_available
            adjustment_entry.calculated_closing = _money_round(closing_balance)
            adjustment_entry.difference = difference
            adjustment_entry.amount = difference
            adjustment_entry.reason = reconciliation_reason
            adjustment_entry.note = reconciliation_reason
            adjustment_entry.edit_count = (adjustment_entry.edit_count or 0) + 1
            db.session.add(CashFlowReconciliationAudit(
                reconciliation_id=adjustment_entry.id,
                adjustment_date=adjustment_date_dt,
                change_type=change_type,
                old_physical_cash=old_physical_cash,
                new_physical_cash=physical_cash_available,
                old_difference=old_difference,
                new_difference=difference,
                old_reason=old_reason,
                new_reason=reconciliation_reason,
                changed_by=username,
                changed_at=pk_model_now(),
            ))
            db.session.commit()
            flash(f'Reconciliation saved for {adjustment_date_dt.strftime("%Y-%m-%d")}. Next day opening will be Rs. {physical_cash_available:,.0f}.', 'success')

    adjustment_entry = CashFlowDifferenceAdjustment.query.filter_by(adjustment_date=adjustment_date_dt).first()
    physical_cash_available = adjustment_entry.physical_cash_available if adjustment_entry and adjustment_entry.physical_cash_available is not None else None
    adjustment_amount = float((adjustment_entry.difference if adjustment_entry and adjustment_entry.difference is not None else adjustment_entry.amount) or 0) if adjustment_entry else 0.0
    reconciliation_reason = (adjustment_entry.reason or adjustment_entry.note or '') if adjustment_entry else ''
    adjusted_closing_balance = physical_cash_available if physical_cash_available is not None else closing_balance

    if export_pdf == '1':
        rendered = render_template('cash_flow.html',
            rows=display_rows,
            from_date=from_date, to_date=to_date,
            filter_type=filter_type,
            opening_balance=opening_balance,
            opening_balance_input=opening_balance_input,
            closing_balance=closing_balance,
            adjustment_amount=adjustment_amount,
            physical_cash_available=physical_cash_available,
            reconciliation_reason=reconciliation_reason,
            adjusted_closing_balance=adjusted_closing_balance,
            adjustment_date_input=adjustment_date_input,
            total_cash_in=total_cash_in,
            total_cash_out=total_cash_out,
            generated_at=pk_now().strftime('%Y-%m-%d %H:%M'),
            pdf_mode=True,
            settings=None,
            fresh_start_date=fresh_start_date,
            fresh_start_cutoff=fresh_start_cutoff,
            fresh_start_clamped=fresh_start_clamped,
            today_opening_override=today_opening_override,
            is_fresh_start_view=(from_date_dt == fresh_start_dt),
        )
        pdf_resp = _try_render_weasy_pdf(rendered, f'cash_flow_{from_date}_{to_date}.pdf')
        if pdf_resp:
            return pdf_resp
        return Response(rendered, content_type='text/html')

    cash_accounts = [
        a for a in Account.query.filter(func.coalesce(Account.is_active, True) == True).order_by(Account.name.asc()).all()
        if (a.category or '').lower() in ('cash', 'bank')
    ]
    cf_categories = CashFlowCategory.query.filter_by(is_active=True).order_by(CashFlowCategory.sort_order, CashFlowCategory.name).all()
    cf_subcategories = CashFlowSubcategory.query.filter_by(is_active=True).order_by(CashFlowSubcategory.name).all()
    cf_parties = CashFlowParty.query.filter_by(is_active=True).order_by(CashFlowParty.name).all()
    breakdown_cat, breakdown_party, breakdown_account = {}, {}, {}
    for r in display_rows:
        ck = (r.get('category') or '—').strip() or '—'
        breakdown_cat.setdefault(ck, {'in': 0.0, 'out': 0.0})
        breakdown_cat[ck]['in'] += float(r.get('cash_in') or 0)
        breakdown_cat[ck]['out'] += float(r.get('cash_out') or 0)
        pk = ((r.get('party_type') or '') + ' · ' + (r.get('party_name') or '—')).strip(' ·')
        breakdown_party.setdefault(pk, {'in': 0.0, 'out': 0.0})
        breakdown_party[pk]['in'] += float(r.get('cash_in') or 0)
        breakdown_party[pk]['out'] += float(r.get('cash_out') or 0)
        ak = (r.get('account_name') or '—').strip() or '—'
        breakdown_account.setdefault(ak, {'in': 0.0, 'out': 0.0})
        breakdown_account[ak]['in'] += float(r.get('cash_in') or 0)
        breakdown_account[ak]['out'] += float(r.get('cash_out') or 0)

    return render_template('cash_flow.html',
        rows=display_rows,
        cash_accounts=cash_accounts,
        cf_categories=cf_categories,
        cf_subcategories=cf_subcategories,
        cf_parties=cf_parties,
        party_types=PARTY_TYPES,
        breakdown_cat=breakdown_cat,
        breakdown_party=breakdown_party,
        breakdown_account=breakdown_account,
        filter_origin=filter_origin,
        filter_category=filter_category,
        filter_subcategory=filter_subcategory,
        filter_party_type=filter_party_type,
        filter_party=filter_party,
        filter_account_id=filter_account_id,
        filter_q=filter_q,
        from_date=from_date, to_date=to_date,
        filter_type=filter_type,
        opening_balance=opening_balance,
        opening_balance_input=opening_balance_input,
        adjustment_amount=adjustment_amount,
        physical_cash_available=physical_cash_available,
        reconciliation_reason=reconciliation_reason,
        show_delete_button=bool(adjustment_entry and adjustment_entry.physical_cash_available is not None),
        adjusted_closing_balance=adjusted_closing_balance,
        adjustment_date_input=adjustment_date_input,
        closing_balance=closing_balance,
        total_cash_in=total_cash_in,
        total_cash_out=total_cash_out,
        generated_at=pk_now().strftime('%Y-%m-%d %H:%M'),
        pdf_mode=False,
        settings=None,
        fresh_start_date=fresh_start_date,
        fresh_start_cutoff=fresh_start_cutoff,
        fresh_start_clamped=fresh_start_clamped,
        today_opening_override=today_opening_override,
        is_fresh_start_view=(from_date_dt == fresh_start_dt),
    )


@bp.route('/cash_flow_differences')
@login_required
def cash_flow_differences():
    from_date = request.args.get('from_date', '').strip()
    to_date = request.args.get('to_date', '').strip()
    workflow_filter = request.args.get('workflow_filter', 'all').strip()
    page = max(1, int(request.args.get('page', 1) or 1))
    per_page = 25

    query = CashFlowDifferenceAdjustment.query
    if from_date:
        try:
            query = query.filter(CashFlowDifferenceAdjustment.adjustment_date >= datetime.strptime(from_date, '%Y-%m-%d').date())
        except Exception:
            from_date = ''
    if to_date:
        try:
            query = query.filter(CashFlowDifferenceAdjustment.adjustment_date <= datetime.strptime(to_date, '%Y-%m-%d').date())
        except Exception:
            to_date = ''
    if workflow_filter == 'new':
        query = query.filter(CashFlowDifferenceAdjustment.physical_cash_available.isnot(None))
    elif workflow_filter == 'legacy':
        query = query.filter(CashFlowDifferenceAdjustment.physical_cash_available.is_(None))
    else:
        workflow_filter = 'all'

    total_count = CashFlowDifferenceAdjustment.query.count()
    new_workflow_count = CashFlowDifferenceAdjustment.query.filter(CashFlowDifferenceAdjustment.physical_cash_available.isnot(None)).count()
    legacy_count = CashFlowDifferenceAdjustment.query.filter(CashFlowDifferenceAdjustment.physical_cash_available.is_(None)).count()
    total_audit_events = CashFlowReconciliationAudit.query.count()

    filtered_count = query.count()
    pages = max(1, (filtered_count + per_page - 1) // per_page)
    page = min(page, pages)
    reconciliations = query.order_by(
        CashFlowDifferenceAdjustment.adjustment_date.desc(),
        CashFlowDifferenceAdjustment.id.desc()
    ).offset((page - 1) * per_page).limit(per_page).all()
    for rec in reconciliations:
        rec.display_opening_balance = _automatic_cash_opening_balance(rec.adjustment_date)
        rec.display_cash_in, rec.display_cash_out = _cash_flow_in_out_between(rec.adjustment_date, rec.adjustment_date)
        if rec.calculated_closing is None:
            rec.display_calculated_closing = rec.display_opening_balance + rec.display_cash_in - rec.display_cash_out
        else:
            rec.display_calculated_closing = rec.calculated_closing

    return render_template(
        'cash_flow_differences.html',
        reconciliations=reconciliations,
        total_count=total_count,
        new_workflow_count=new_workflow_count,
        legacy_count=legacy_count,
        total_audit_events=total_audit_events,
        from_date=from_date,
        to_date=to_date,
        workflow_filter=workflow_filter,
        page=page,
        pages=pages,
    )


@bp.route('/cash_flow_differences/<int:rec_id>')
@login_required
def cash_flow_reconciliation_detail(rec_id):
    reconciliation = CashFlowDifferenceAdjustment.query.get_or_404(rec_id)
    audit_trail = CashFlowReconciliationAudit.query.filter_by(
        adjustment_date=reconciliation.adjustment_date
    ).order_by(CashFlowReconciliationAudit.changed_at.asc(), CashFlowReconciliationAudit.id.asc()).all()
    return render_template(
        'cash_flow_reconciliation_detail.html',
        reconciliation=reconciliation,
        audit_trail=audit_trail,
    )


