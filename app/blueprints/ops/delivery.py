"""delivery — split from ops.py."""
from ._common import *  # noqa

@bp.route('/delivery_rents')
@login_required
def delivery_rents_page():
    if not _user_can('can_view_delivery_rent'):
        flash('Unauthorized', 'danger')
        return redirect(url_for('index'))

    date_from = (request.args.get('date_from') or '').strip()
    date_to = (request.args.get('date_to') or '').strip()
    driver = (request.args.get('driver') or '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    per_page = min(max(per_page, 10), 50)

    q = SaleDeliveryPerson.query.options(
        selectinload(SaleDeliveryPerson.sale).selectinload(DirectSale.invoice),
        selectinload(SaleDeliveryPerson.delivery_person)
    ).join(DirectSale, SaleDeliveryPerson.sale_id == DirectSale.id).filter(
        SaleDeliveryPerson.is_void == False
    )
    if date_from:
        q = q.filter(func.date(SaleDeliveryPerson.created_at) >= date_from)
    if date_to:
        q = q.filter(func.date(SaleDeliveryPerson.created_at) <= date_to)
    if driver:
        q = q.join(DeliveryPerson, SaleDeliveryPerson.delivery_person_id == DeliveryPerson.id).filter(
            func.lower(func.trim(DeliveryPerson.name)) == driver.lower()
        )

    total_rent = float(q.with_entities(func.sum(SaleDeliveryPerson.rent_amount)).scalar() or 0)
    pagination = q.order_by(SaleDeliveryPerson.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    rows = pagination.items

    payment_totals = {}
    if rows:
        alloc_ids = [r.id for r in rows]
        pay_rows = db.session.query(
            DeliveryPersonPayment.allocation_id,
            func.sum(DeliveryPersonPayment.amount_paid),
            func.sum(DeliveryPersonPayment.waive_off_amount)
        ).filter(
            DeliveryPersonPayment.is_void == False,
            DeliveryPersonPayment.allocation_id.in_(alloc_ids)
        ).group_by(DeliveryPersonPayment.allocation_id).all()
        for alloc_id, paid_sum, waive_sum in pay_rows:
            payment_totals[alloc_id] = {
                'paid': float(paid_sum or 0),
                'waived': float(waive_sum or 0)
            }

    paid_query = db.session.query(
        func.sum(DeliveryPersonPayment.amount_paid),
        func.sum(DeliveryPersonPayment.waive_off_amount)
    ).join(
        SaleDeliveryPerson, DeliveryPersonPayment.allocation_id == SaleDeliveryPerson.id
    ).filter(
        DeliveryPersonPayment.is_void == False,
        SaleDeliveryPerson.is_void == False
    )
    if date_from:
        paid_query = paid_query.filter(func.date(SaleDeliveryPerson.created_at) >= date_from)
    if date_to:
        paid_query = paid_query.filter(func.date(SaleDeliveryPerson.created_at) <= date_to)
    if driver:
        paid_query = paid_query.join(DeliveryPerson, SaleDeliveryPerson.delivery_person_id == DeliveryPerson.id).filter(
            func.lower(func.trim(DeliveryPerson.name)) == driver.lower()
        )
    paid_sum_all, waived_sum_all = paid_query.first() or (0, 0)
    total_paid = float(paid_sum_all or 0)
    total_waived = float(waived_sum_all or 0)
    total_due = max(0.0, total_rent - total_paid - total_waived)

    for r in rows:
        totals = payment_totals.get(r.id, {'paid': 0.0, 'waived': 0.0})
        r.paid_total = float(totals.get('paid', 0) or 0)
        r.waive_total = float(totals.get('waived', 0) or 0)
        r.due_total = max(0.0, float(r.rent_amount or 0) - r.paid_total - r.waive_total)

    totals_rows = db.session.query(
        DeliveryPerson.name,
        func.sum(SaleDeliveryPerson.rent_amount)
    ).join(SaleDeliveryPerson, SaleDeliveryPerson.delivery_person_id == DeliveryPerson.id).filter(
        SaleDeliveryPerson.is_void == False
    )
    if date_from:
        totals_rows = totals_rows.filter(func.date(SaleDeliveryPerson.created_at) >= date_from)
    if date_to:
        totals_rows = totals_rows.filter(func.date(SaleDeliveryPerson.created_at) <= date_to)
    if driver:
        totals_rows = totals_rows.filter(func.lower(func.trim(DeliveryPerson.name)) == driver.lower())
    totals_by_driver = totals_rows.group_by(DeliveryPerson.name).order_by(
        func.sum(SaleDeliveryPerson.rent_amount).desc()
    ).all()

    active_driver_names = {
        (name or '').strip()
        for (name,) in db.session.query(DeliveryPerson.name).filter(
            DeliveryPerson.is_active == True
        ).all()
        if (name or '').strip()
    }
    historical_driver_names = {
        (name or '').strip()
        for (name,) in db.session.query(DeliveryPerson.name).join(
            SaleDeliveryPerson, SaleDeliveryPerson.delivery_person_id == DeliveryPerson.id
        ).filter(
            SaleDeliveryPerson.is_void == False
        ).distinct().all()
        if (name or '').strip()
    }
    driver_names = sorted(active_driver_names | historical_driver_names)

    return render_template(
        'delivery_rents.html',
        rows=rows,
        total_rent=total_rent,
        total_paid=total_paid,
        total_waived=total_waived,
        total_due=total_due,
        totals_by_driver=totals_by_driver,
        driver_names=driver_names,
        date_from=date_from,
        date_to=date_to,
        driver_filter=driver,
        pagination=pagination,
        per_page=per_page
    )


@bp.route('/delivery_rents/void/<int:id>', methods=['POST'])
@login_required
def void_delivery_rent(id):
    if not _user_can('can_manage_sales'):
        flash('Permission denied', 'danger')
        return redirect(url_for('delivery_rents_page'))
    row = db.session.get(SaleDeliveryPerson, id)
    if row:
        row.is_void = True
        db.session.commit()
        flash('Delivery rent entry deleted.', 'success')
    return redirect(url_for('delivery_rents_page'))


@bp.route('/delivery_rents/pay/<int:alloc_id>', methods=['POST'])
@login_required
def pay_delivery_rent(alloc_id):
    if not _user_can('can_manage_sales'):
        flash('Permission denied', 'danger')
        return redirect(url_for('delivery_rents_page'))

    alloc = db.session.get(SaleDeliveryPerson, alloc_id)
    if not alloc or alloc.is_void:
        flash('Invalid delivery rent entry.', 'danger')
        return redirect(url_for('delivery_rents_page'))

    try:
        paid_amount = float(request.form.get('paid_amount', 0) or 0)
    except ValueError:
        paid_amount = 0
    try:
        waive_amount = float(request.form.get('waive_off_amount', 0) or 0)
    except ValueError:
        waive_amount = 0

    if paid_amount < 0 or waive_amount < 0:
        flash('Amounts cannot be negative.', 'danger')
        return redirect(url_for('delivery_rents_page'))

    existing = db.session.query(
        func.sum(DeliveryPersonPayment.amount_paid),
        func.sum(DeliveryPersonPayment.waive_off_amount)
    ).filter(
        DeliveryPersonPayment.is_void == False,
        DeliveryPersonPayment.allocation_id == alloc_id
    ).first()
    already_paid = float(existing[0] or 0) if existing else 0.0
    already_waived = float(existing[1] or 0) if existing else 0.0
    max_payable = max(0.0, float(alloc.rent_amount or 0) - already_paid - already_waived)

    if paid_amount + waive_amount <= 0:
        flash('Enter paid or waive-off amount.', 'danger')
        return redirect(url_for('delivery_rents_page'))
    if paid_amount + waive_amount > max_payable + 0.0001:
        flash('Paid + waive-off exceeds due amount.', 'danger')
        return redirect(url_for('delivery_rents_page'))

    note = (request.form.get('note') or '').strip()
    date_str = (request.form.get('date') or '').strip()
    pay_dt = resolve_posted_datetime(date_str) if date_str else pk_now()

    db.session.add(DeliveryPersonPayment(
        delivery_person_id=alloc.delivery_person_id,
        sale_id=alloc.sale_id,
        allocation_id=alloc.id,
        amount_paid=paid_amount,
        waive_off_amount=waive_amount,
        note=note,
        date_posted=pay_dt,
        created_by=(current_user.username if current_user and current_user.is_authenticated else None),
        is_void=False
    ))
    db.session.commit()
    flash('Delivery rent payment recorded.', 'success')
    return redirect(url_for('delivery_rents_page'))


