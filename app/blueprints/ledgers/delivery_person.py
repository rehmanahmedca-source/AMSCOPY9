"""Delivery-person financial ledger routes."""
from ._common import *  # noqa

import csv
from io import StringIO
from datetime import datetime

from app.services.financial_ledgers import (
    build_delivery_person_financial_ledger,
    filter_ledger_rows,
)


def _driver_filters():
    return {
        'start_date': (request.args.get('start_date') or request.args.get('date_from') or '').strip(),
        'end_date': (request.args.get('end_date') or request.args.get('date_to') or '').strip(),
        'type_filter': (request.args.get('type') or request.args.get('transaction_type') or '').strip(),
        'query': (request.args.get('q') or request.args.get('search') or '').strip(),
        'amount_min': (request.args.get('amount_min') or '').strip(),
        'amount_max': (request.args.get('amount_max') or '').strip(),
        'account_filter': (request.args.get('account') or '').strip(),
        'status_filter': (request.args.get('status') or '').strip(),
    }


def _driver_page(ledger, filters):
    selected = ledger['filtered_rows']
    page = max(request.args.get('page', 1, type=int) or 1, 1)
    per_page = min(max(request.args.get('per_page', 25, type=int) or 25, 10), 100)
    total = len(selected)
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    rows = selected[(page - 1) * per_page: page * per_page]
    closing = rows[-1]['balance'] if rows else ledger['closing_balance']
    return rows, page, per_page, total, pages, closing


def _render_driver_ledger(person, *, filters=None):
    filters = filters or _driver_filters()
    ledger = build_delivery_person_financial_ledger(person, **filters)
    rows, page, per_page, total, pages, closing = _driver_page(ledger, filters)
    people = DeliveryPerson.query.order_by(DeliveryPerson.name.asc(), DeliveryPerson.id.asc()).all()
    return render_template(
        'financial_ledger.html',
        entity=person,
        entity_type='delivery_person',
        ledger=ledger,
        rows=rows,
        all_rows=ledger['rows'],
        obligations=[],
        filters=filters,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=pages,
        filtered_closing=closing,
        selector_entities=people,
        current_payable=max(0.0, float(ledger['closing_balance'] or 0)),
        back_url=url_for('delivery_persons_page'),
        opening_url=url_for('delivery_person_opening_balance', id=person.id),
        today_date=pk_today().strftime('%Y-%m-%d'),
    )


@bp.route('/delivery_person_ledger/<int:id>')
@bp.route('/delivery_ledger/<int:id>')
@login_required
def delivery_person_ledger(id):
    if not _user_can('can_view_delivery_rent') and not _user_can('can_view_client_ledger'):
        flash('Permission denied', 'danger')
        return redirect(url_for('index'))
    person = DeliveryPerson.query.get_or_404(id)
    requested_person = (request.args.get('driver_search') or '').strip()
    if requested_person:
        alternate = DeliveryPerson.query.filter(
            func.lower(func.trim(DeliveryPerson.name)) == requested_person.casefold()
        ).first()
        if alternate and alternate.id != person.id:
            preserved = request.args.to_dict()
            preserved.pop('driver_search', None)
            return redirect(url_for('delivery_person_ledger', id=alternate.id, **preserved))
    return _render_driver_ledger(person)


@bp.route('/delivery_person_opening_balance/<int:id>', methods=['POST'])
@login_required
def delivery_person_opening_balance(id):
    if not _user_can('can_manage_delivery_persons'):
        flash('Permission denied', 'danger')
        return redirect(url_for('delivery_person_ledger', id=id))
    person = DeliveryPerson.query.get_or_404(id)
    person.opening_balance = _to_float_or_zero(request.form.get('opening_balance', 0))
    person.opening_balance_date = _resolve_opening_balance_date(
        request.form.get('opening_balance_date'),
        fallback_dt=person.opening_balance_date or person.created_at,
    )
    db.session.commit()
    flash('Delivery person opening balance updated.', 'success')
    return redirect(url_for('delivery_person_ledger', id=id))


@bp.route('/delivery_person_ledger/<int:id>/pay', methods=['POST'])
@login_required
def settle_delivery_person(id):
    """Allocate a consolidated settlement FIFO across active rent allocations."""
    if not _user_can('can_manage_sales'):
        flash('Permission denied', 'danger')
        return redirect(url_for('delivery_person_ledger', id=id))
    person = DeliveryPerson.query.get_or_404(id)
    try:
        paid = max(0.0, float(request.form.get('paid_amount', 0) or 0))
        waived = max(0.0, float(request.form.get('waive_off_amount', 0) or 0))
    except (TypeError, ValueError):
        paid = waived = 0.0
    if paid + waived <= 0:
        flash('Enter a payment or waive-off amount.', 'danger')
        return redirect(url_for('delivery_person_ledger', id=id))

    allocations = SaleDeliveryPerson.query.filter_by(
        delivery_person_id=person.id, is_void=False
    ).join(DirectSale, SaleDeliveryPerson.sale_id == DirectSale.id).filter(
        DirectSale.is_void == False,
        SaleDeliveryPerson.rent_amount > 0,
    ).order_by(SaleDeliveryPerson.created_at.asc(), SaleDeliveryPerson.id.asc()).all()
    remaining = paid + waived
    created = 0
    for alloc in allocations:
        totals = db.session.query(
            func.coalesce(func.sum(DeliveryPersonPayment.amount_paid), 0),
            func.coalesce(func.sum(DeliveryPersonPayment.waive_off_amount), 0),
        ).filter(
            DeliveryPersonPayment.is_void == False,
            DeliveryPersonPayment.allocation_id == alloc.id,
        ).first()
        due = max(0.0, float(alloc.rent_amount or 0) - float(totals[0] or 0) - float(totals[1] or 0))
        if due <= 0:
            continue
        allocation_amount = min(due, remaining)
        allocation_paid = min(paid, allocation_amount)
        allocation_waived = allocation_amount - allocation_paid
        db.session.add(DeliveryPersonPayment(
            delivery_person_id=person.id,
            sale_id=alloc.sale_id,
            allocation_id=alloc.id,
            amount_paid=allocation_paid,
            waive_off_amount=allocation_waived,
            note=(request.form.get('note') or '').strip(),
            date_posted=resolve_posted_datetime(request.form.get('date')) if request.form.get('date') else pk_now(),
            created_by=(current_user.username if current_user and current_user.is_authenticated else None),
            is_void=False,
        ))
        db.session.flush()
        created += 1
        paid -= allocation_paid
        waived -= allocation_waived
        remaining -= allocation_amount
        if remaining <= 0.0001:
            break
    if remaining > 0.0001:
        # Older installations may have rent rows without a
        # SaleDeliveryPerson allocation.  Preserve those sources and attach a
        # settlement to the delivery person/sale without inventing an
        # allocation id.
        active_sale_ids = {a.sale_id for a in allocations}
        legacy_rents = DeliveryRent.query.filter(
            DeliveryRent.is_void == False,
            func.lower(func.trim(DeliveryRent.delivery_person_name)) == person.name.casefold(),
        ).order_by(DeliveryRent.date_posted.asc(), DeliveryRent.id.asc()).all()
        for rent in legacy_rents:
            if rent.sale_id in active_sale_ids:
                continue
            existing_paid, existing_waived = db.session.query(
                func.coalesce(func.sum(DeliveryPersonPayment.amount_paid), 0),
                func.coalesce(func.sum(DeliveryPersonPayment.waive_off_amount), 0),
            ).filter(
                DeliveryPersonPayment.is_void == False,
                DeliveryPersonPayment.allocation_id.is_(None),
                DeliveryPersonPayment.sale_id == rent.sale_id,
                DeliveryPersonPayment.delivery_person_id == person.id,
            ).first()
            due = max(0.0, float(rent.amount or 0) - float(existing_paid or 0) - float(existing_waived or 0))
            if due <= 0:
                continue
            allocation_amount = min(due, remaining)
            allocation_paid = min(paid, allocation_amount)
            allocation_waived = allocation_amount - allocation_paid
            db.session.add(DeliveryPersonPayment(
                delivery_person_id=person.id, sale_id=rent.sale_id, allocation_id=None,
                amount_paid=allocation_paid, waive_off_amount=allocation_waived,
                note=(request.form.get('note') or '').strip(),
                date_posted=resolve_posted_datetime(request.form.get('date')) if request.form.get('date') else pk_now(),
                created_by=(current_user.username if current_user and current_user.is_authenticated else None),
                is_void=False,
            ))
            db.session.flush()
            created += 1
            paid -= allocation_paid
            waived -= allocation_waived
            remaining -= allocation_amount
            if remaining <= 0.0001:
                break
    if remaining > 0.0001:
        db.session.rollback()
        flash('Settlement exceeds the currently outstanding delivery-person balance.', 'danger')
        return redirect(url_for('delivery_person_ledger', id=id))
    db.session.commit()
    flash(f'Delivery person settlement allocated across {created} rent item(s).', 'success')
    return redirect(url_for('delivery_person_ledger', id=id))


@bp.route('/delivery_person_payments/<int:id>/edit', methods=['POST'])
@login_required
def edit_delivery_person_payment(id):
    if not _user_can('can_manage_sales'):
        flash('Permission denied', 'danger')
        return redirect(url_for('delivery_persons_page'))
    payment = DeliveryPersonPayment.query.get_or_404(id)
    if payment.is_void:
        flash('Restore the settlement before editing it.', 'danger')
        return redirect(url_for('delivery_person_ledger', id=payment.delivery_person_id))
    try:
        paid = max(0.0, float(request.form.get('amount_paid', 0) or 0))
        waived = max(0.0, float(request.form.get('waive_off_amount', 0) or 0))
    except (TypeError, ValueError):
        flash('Settlement amounts must be valid numbers.', 'danger')
        return redirect(url_for('delivery_person_ledger', id=payment.delivery_person_id))
    if paid + waived <= 0:
        flash('Enter a payment or waive-off amount.', 'danger')
        return redirect(url_for('delivery_person_ledger', id=payment.delivery_person_id))
    if payment.allocation_id:
        allocation = db.session.get(SaleDeliveryPerson, payment.allocation_id)
        totals = db.session.query(
            func.coalesce(func.sum(DeliveryPersonPayment.amount_paid), 0),
            func.coalesce(func.sum(DeliveryPersonPayment.waive_off_amount), 0),
        ).filter(
            DeliveryPersonPayment.is_void == False,
            DeliveryPersonPayment.allocation_id == payment.allocation_id,
            DeliveryPersonPayment.id != payment.id,
        ).first()
        due = max(0.0, float(getattr(allocation, 'rent_amount', 0) or 0) - float(totals[0] or 0) - float(totals[1] or 0)) if allocation else 0.0
        if paid + waived > due + 0.0001:
            flash('Updated settlement exceeds the remaining rent amount.', 'danger')
            return redirect(url_for('delivery_person_ledger', id=payment.delivery_person_id))
    payment.amount_paid = paid
    payment.waive_off_amount = waived
    payment.note = (request.form.get('note') or '').strip()
    payment.date_posted = resolve_posted_datetime(request.form.get('date')) if request.form.get('date') else (payment.date_posted or pk_now())
    db.session.commit()
    flash('Delivery person settlement updated.', 'success')
    return redirect(url_for('delivery_person_ledger', id=payment.delivery_person_id))


@bp.route('/delivery_person_payments/<int:id>/void', methods=['POST'])
@login_required
def void_delivery_person_payment(id):
    if not _user_can('can_manage_sales'):
        flash('Permission denied', 'danger')
        return redirect(url_for('delivery_persons_page'))
    payment = DeliveryPersonPayment.query.get_or_404(id)
    payment.is_void = True
    db.session.commit()
    flash('Delivery person settlement reversed; history was preserved.', 'success')
    return redirect(url_for('delivery_person_ledger', id=payment.delivery_person_id))


@bp.route('/delivery_person_payments/<int:id>/restore', methods=['POST'])
@login_required
def restore_delivery_person_payment(id):
    if not _user_can('can_manage_sales'):
        flash('Permission denied', 'danger')
        return redirect(url_for('delivery_persons_page'))
    payment = DeliveryPersonPayment.query.get_or_404(id)
    if not payment.is_void:
        flash('Settlement is already active.', 'warning')
        return redirect(url_for('delivery_person_ledger', id=payment.delivery_person_id))
    if payment.allocation_id:
        allocation = db.session.get(SaleDeliveryPerson, payment.allocation_id)
        other_paid, other_waived = db.session.query(
            func.coalesce(func.sum(DeliveryPersonPayment.amount_paid), 0),
            func.coalesce(func.sum(DeliveryPersonPayment.waive_off_amount), 0),
        ).filter(
            DeliveryPersonPayment.is_void == False,
            DeliveryPersonPayment.allocation_id == payment.allocation_id,
        ).first()
        if allocation and float(other_paid or 0) + float(other_waived or 0) + float(payment.amount_paid or 0) + float(payment.waive_off_amount or 0) > float(allocation.rent_amount or 0) + 0.0001:
            flash('Settlement cannot be restored because the allocation is already settled by another row.', 'danger')
            return redirect(url_for('delivery_person_ledger', id=payment.delivery_person_id))
    payment.is_void = False
    db.session.commit()
    flash('Delivery person settlement restored.', 'success')
    return redirect(url_for('delivery_person_ledger', id=payment.delivery_person_id))


@bp.route('/download_delivery_person_ledger/<int:id>')
@login_required
def download_delivery_person_ledger(id):
    person = DeliveryPerson.query.get_or_404(id)
    filters = _driver_filters()
    ledger = build_delivery_person_financial_ledger(person, **filters)
    action = (request.args.get('action') or 'download').lower()
    if action != 'print':
        out = StringIO(newline='')
        writer = csv.writer(out)
        writer.writerow(['Date', 'Type', 'Reference', 'Description', 'Debit', 'Credit', 'Balance', 'Notes'])
        for row in ledger['filtered_rows']:
            writer.writerow([
                row['date'].strftime('%Y-%m-%d %H:%M') if row.get('date') and row['date'] != datetime.min else '',
                row.get('type', ''), row.get('reference', ''), row.get('description', ''),
                f"{row.get('debit', 0):.2f}", f"{row.get('credit', 0):.2f}",
                f"{row.get('balance', 0):.2f}", row.get('note', ''),
            ])
        response = Response(out.getvalue(), mimetype='text/csv; charset=utf-8')
        response.headers['Content-Disposition'] = 'attachment; filename=delivery-person-ledger.csv'
        return response
    # Print/download HTML remains dependency-free and can be printed by any
    # browser, just like the legacy ledger fallback.
    rendered = render_template(
        'supplier_ledger_print.html',
        supplier=person,
        ledger=ledger['filtered_rows'],
        final_balance=ledger['closing_balance'],
        total_bill=ledger['total_debit'],
        total_paid=ledger['total_credit'],
        generated_at=pk_now(), auto_print=True,
    )
    response = make_response(rendered)
    response.headers['Content-Disposition'] = 'inline; filename=delivery-person-ledger.html'
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    return response


@bp.route('/api/delivery_persons/search')
@login_required
def delivery_person_search_api():
    query = (request.args.get('q') or '').strip()
    people = DeliveryPerson.query
    if query:
        people = people.filter(DeliveryPerson.name.ilike(f'%{query}%'))
    return jsonify([{
        'id': person.id, 'name': person.name, 'phone': person.phone or '', 'is_active': bool(person.is_active)
    } for person in people.order_by(DeliveryPerson.name.asc()).limit(25).all()])


@bp.route('/api/delivery_person_ledger/<int:id>')
@login_required
def delivery_person_ledger_api(id):
    person = DeliveryPerson.query.get_or_404(id)
    ledger = build_delivery_person_financial_ledger(person)
    return jsonify({
        'ok': True,
        'delivery_person': {'id': person.id, 'name': person.name, 'phone': person.phone or ''},
        'opening_balance': float(person.opening_balance or 0),
        'total_debit': ledger['total_debit'],
        'total_credit': ledger['total_credit'],
        'closing_balance': ledger['closing_balance'],
        'status': ledger['status'],
        'rows': [{
            'date': row['date'].isoformat() if row.get('date') and row['date'] != datetime.min else None,
            'type': row.get('type'), 'reference': row.get('reference'),
            'description': row.get('description'), 'debit': row.get('debit', 0),
            'credit': row.get('credit', 0), 'balance': row.get('balance', 0),
            'source_type': row.get('source_type'), 'source_id': row.get('source_id'),
            'note': row.get('note') or '',
        } for row in ledger['rows']],
    })
