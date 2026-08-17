from ._common import *  # noqa

@bp.route('/add_supplier', methods=['POST'])
@login_required
def add_supplier():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Supplier name is required', 'danger')
        return redirect(url_for('suppliers'))
    
    existing = Supplier.query.filter(func.lower(Supplier.name) == name.lower()).first()
    if existing:
        if request.args.get('ajax'):
            return jsonify({'success': True, 'id': existing.id, 'name': existing.name})
        flash('Supplier already exists', 'warning')
        return redirect(url_for('suppliers'))

    new_s = Supplier(
        name=name,
        phone=request.form.get('phone', ''),
        address=request.form.get('address', ''),
        opening_balance=_to_float_or_zero(request.form.get('opening_balance', 0)),
        opening_balance_date=_resolve_opening_balance_date(request.form.get('opening_balance_date')),
        is_active=True
    )
    db.session.add(new_s)
    db.session.commit()
    
    if request.args.get('ajax'):
        return jsonify({'success': True, 'id': new_s.id, 'name': new_s.name})
        
    flash('Supplier Added', 'success')
    return redirect(url_for('suppliers'))

