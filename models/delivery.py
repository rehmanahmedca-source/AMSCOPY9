from .__base import *  # noqa
from .helpers import *  # noqa

class DeliveryRent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('direct_sale.id'), nullable=True, index=True)
    delivery_person_name = db.Column(db.String(100), nullable=False, index=True)
    bill_no = db.Column(db.String(50), index=True)
    amount = db.Column(db.Float, default=0)
    note = db.Column(db.String(500))
    date_posted = db.Column(db.DateTime, default=pk_model_now, index=True)
    created_by = db.Column(db.String(80))
    is_void = db.Column(db.Boolean, default=False, index=True)

    sale = db.relationship('DirectSale', backref=db.backref('delivery_rents', lazy=True))


class SaleDeliveryPerson(db.Model):
    __tablename__ = 'sale_delivery_persons'
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('direct_sale.id'), nullable=False, index=True)
    delivery_person_id = db.Column(db.Integer, db.ForeignKey('delivery_person.id'), nullable=False, index=True)
    bags_delivered = db.Column(db.Float, default=0)
    rent_amount = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=pk_model_now, index=True)
    is_void = db.Column(db.Boolean, default=False, index=True)

    sale = db.relationship('DirectSale', backref=db.backref('delivery_person_allocations', lazy=True))
    delivery_person = db.relationship('DeliveryPerson')


class DeliveryPersonPayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    delivery_person_id = db.Column(db.Integer, db.ForeignKey('delivery_person.id'), nullable=False, index=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('direct_sale.id'), nullable=True, index=True)
    allocation_id = db.Column(db.Integer, db.ForeignKey('sale_delivery_persons.id'), nullable=True, index=True)
    amount_paid = db.Column(db.Float, default=0)
    waive_off_amount = db.Column(db.Float, default=0)
    note = db.Column(db.String(500))
    date_posted = db.Column(db.DateTime, default=pk_model_now, index=True)
    created_by = db.Column(db.String(80))
    is_void = db.Column(db.Boolean, default=False, index=True)

    delivery_person = db.relationship('DeliveryPerson')
    sale = db.relationship('DirectSale')
    allocation = db.relationship('SaleDeliveryPerson')

