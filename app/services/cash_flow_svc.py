"""Domain service module — extracted from legacy ERP core."""
from __future__ import annotations

import os
import io
import secrets
import json
import calendar
import threading
import time
import smtplib
import shutil
import sqlite3
import zipfile
import urllib.request
import urllib.error
import re
import logging
import importlib
from itertools import zip_longest
from urllib.parse import unquote
from contextlib import redirect_stderr
from email.message import EmailMessage
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo
from sqlalchemy import func, case, text, or_, and_, exists, not_
from sqlalchemy.orm import selectinload
from types import SimpleNamespace
from flask import (
    current_app as app,
    render_template, request, redirect, url_for, flash, jsonify,
    send_file, Response, make_response, send_from_directory,
    got_request_exception, abort, session, g,
)
from flask_login import login_user, login_required, logout_user, current_user

from models import *
from utils.audit import audit_log
from utils.reconciliation import run_auto_reconcile
from cash_flow_reconciliation_helpers import (
    create_reconciliation, update_reconciliation, delete_reconciliation,
    get_reconciliation_history, migrate_legacy_record,
)
from app.services import constants as C
from app.services import state

# === explicit service imports ===
from app.services.time_money import (
    _money_round,
    pk_now,
)


# Rebind constants used as bare names
OPEN_KHATA_CODE = C.OPEN_KHATA_CODE
OPEN_KHATA_NAME = C.OPEN_KHATA_NAME
PK_TZ = C.PK_TZ
SALE_CATEGORY_CHOICES = C.SALE_CATEGORY_CHOICES
_SALE_CATEGORY_ALIASES = C._SALE_CATEGORY_ALIASES
DOMAIN_WIPE_REGISTRY = C.DOMAIN_WIPE_REGISTRY
USER_PERMISSION_DEFAULTS = C.USER_PERMISSION_DEFAULTS
PERMISSION_LEGACY_FALLBACKS = C.PERMISSION_LEGACY_FALLBACKS
ENDPOINT_PERMISSION_MAP = C.ENDPOINT_PERMISSION_MAP
AUTO_BILL_NS_DEFAULT = C.AUTO_BILL_NS_DEFAULT
AUTO_BILL_NAMESPACES = C.AUTO_BILL_NAMESPACES
EDITABLE_USER_PERMISSION_FIELDS = C.EDITABLE_USER_PERMISSION_FIELDS
basedir = C.basedir
legacy_instance_dir = C.legacy_instance_dir
legacy_db_path = C.legacy_db_path
db_path = C.db_path
_DB_HEALTH_SNAPSHOT_PATH = C._DB_HEALTH_SNAPSHOT_PATH
_max_upload_mb = C._max_upload_mb
_AUTO_BACKUP_ENABLED = C._AUTO_BACKUP_ENABLED
_WIPE_BACKUP_ENABLED = C._WIPE_BACKUP_ENABLED
_AUTO_RECONCILE_ENABLED = C._AUTO_RECONCILE_ENABLED
_AUTO_RECONCILE_FIX = C._AUTO_RECONCILE_FIX
_AUTO_RECONCILE_INTERVAL_SEC = C._AUTO_RECONCILE_INTERVAL_SEC
_AUTO_RECONCILE_TOL = C._AUTO_RECONCILE_TOL
_ALLOW_EMPTY_DB = C._ALLOW_EMPTY_DB
_ALLOW_DB_DROP = C._ALLOW_DB_DROP
_DB_HEALTH_DROP_RATIO = C._DB_HEALTH_DROP_RATIO
_DB_HEALTH_DROP_MIN = C._DB_HEALTH_DROP_MIN
_DB_HEALTH_MIN_BYTES = C._DB_HEALTH_MIN_BYTES

def _cash_flow_net_between(start_date=None, end_date=None):
    """Net cash movement for the same transaction sources shown in Cash Flow."""
    if end_date and start_date and start_date > end_date:
        return 0.0

    def _date_filters(column):
        filters = []
        if start_date:
            filters.append(func.date(column) >= start_date.strftime('%Y-%m-%d'))
        if end_date:
            filters.append(func.date(column) <= end_date.strftime('%Y-%m-%d'))
        return filters

    cash_method_clauses = [
        func.lower(func.trim(func.coalesce(Payment.method, ''))) == 'cash',
        func.lower(func.trim(func.coalesce(Payment.method, ''))) == 'cash sale',
    ]
    payment_in = float(Payment.query.filter(
        Payment.is_void == False,
        or_(*cash_method_clauses),
        *_date_filters(Payment.date_posted)
    ).with_entities(func.sum(Payment.amount)).scalar() or 0)

    sale_in = float(DirectSale.query.filter(
        DirectSale.is_void == False,
        or_(
            func.lower(func.trim(func.coalesce(DirectSale.category, ''))) == 'cash',
            func.lower(func.trim(func.coalesce(DirectSale.category, ''))) == 'cash sale',
            func.lower(func.trim(func.coalesce(DirectSale.payment_method, ''))) == 'cash',
            func.lower(func.trim(func.coalesce(DirectSale.payment_method, ''))) == 'cash sale',
        ),
        DirectSale.paid_amount > 0,
        *_date_filters(DirectSale.date_posted)
    ).with_entities(func.sum(DirectSale.paid_amount)).scalar() or 0)

    supplier_out = float(SupplierPayment.query.filter(
        SupplierPayment.is_void == False,
        *_date_filters(SupplierPayment.date_posted)
    ).with_entities(func.sum(SupplierPayment.amount)).scalar() or 0)

    account_in = 0.0
    account_out = 0.0
    fbm_drawer_account = Account.query.filter(
        func.lower(func.trim(Account.name)) == 'fbm drawer cash'
    ).first() or Account.query.filter(Account.name.ilike('%fbm drawer cash%')).first()
    fbm_drawer_account_id = fbm_drawer_account.id if fbm_drawer_account else None

    account_txs = AccountTransaction.query.filter(
        AccountTransaction.is_void == False,
        AccountTransaction.transaction_type.in_(['Expense', 'Payment', 'Transfer']),
        *_date_filters(AccountTransaction.date_posted)
    ).all()
    account_cache = {}
    for tx in account_txs:
        amount = float(tx.amount or 0)
        if tx.transaction_type == 'Transfer' and fbm_drawer_account_id is not None:
            if tx.to_account_id == fbm_drawer_account_id and tx.from_account_id != fbm_drawer_account_id:
                account_in += amount
            elif tx.from_account_id == fbm_drawer_account_id and tx.to_account_id != fbm_drawer_account_id:
                account_out += amount
            continue

        note_u = (tx.note or '').upper()
        if any(marker in note_u for marker in (
            '[SRC:BOOKING:',
            '[SRC:DIRECTSALE:',
            '[SRC:PAYMENT:',
            '[SRC:SUPPLIERPAYMENT:',
            '[SRC:CLIENTREFUND:',
        )):
            continue
        if tx.transaction_type == 'Receipt' and tx.to_account_id is not None:
            if tx.to_account_id not in account_cache:
                account_cache[tx.to_account_id] = Account.query.get(tx.to_account_id)
            acc = account_cache.get(tx.to_account_id)
            if acc and (acc.category or '').lower() in ('cash', 'bank'):
                account_in += amount
            continue
        if tx.transaction_type in ['Expense', 'Payment'] and tx.from_account_id is not None:
            if tx.from_account_id not in account_cache:
                account_cache[tx.from_account_id] = Account.query.get(tx.from_account_id)
            acc = account_cache.get(tx.from_account_id)
            if acc and (acc.category or '').lower() in ('cash', 'bank'):
                account_out += amount

    return payment_in + sale_in + account_in - supplier_out - account_out


def _legacy_adjustments_total(start_date=None, end_date=None):
    query = CashFlowDifferenceAdjustment.query.filter(
        CashFlowDifferenceAdjustment.physical_cash_available.is_(None)
    )
    if start_date:
        query = query.filter(CashFlowDifferenceAdjustment.adjustment_date >= start_date)
    if end_date:
        query = query.filter(CashFlowDifferenceAdjustment.adjustment_date <= end_date)
    return float(query.with_entities(func.coalesce(func.sum(CashFlowDifferenceAdjustment.amount), 0)).scalar() or 0)


def _cash_flow_in_out_between(start_date, end_date):
    """Cash-in and cash-out totals for the history page using cash-flow sources."""
    if end_date and start_date and start_date > end_date:
        return 0.0, 0.0

    def _date_filters(column):
        filters = []
        if start_date:
            filters.append(func.date(column) >= start_date.strftime('%Y-%m-%d'))
        if end_date:
            filters.append(func.date(column) <= end_date.strftime('%Y-%m-%d'))
        return filters

    cash_method_clauses = [
        func.lower(func.trim(func.coalesce(Payment.method, ''))) == 'cash',
        func.lower(func.trim(func.coalesce(Payment.method, ''))) == 'cash sale',
    ]
    cash_in = float(Payment.query.filter(
        Payment.is_void == False,
        or_(*cash_method_clauses),
        *_date_filters(Payment.date_posted)
    ).with_entities(func.sum(Payment.amount)).scalar() or 0)
    cash_in += float(DirectSale.query.filter(
        DirectSale.is_void == False,
        or_(
            func.lower(func.trim(func.coalesce(DirectSale.category, ''))) == 'cash',
            func.lower(func.trim(func.coalesce(DirectSale.category, ''))) == 'cash sale',
            func.lower(func.trim(func.coalesce(DirectSale.payment_method, ''))) == 'cash',
            func.lower(func.trim(func.coalesce(DirectSale.payment_method, ''))) == 'cash sale',
        ),
        DirectSale.paid_amount > 0,
        *_date_filters(DirectSale.date_posted)
    ).with_entities(func.sum(DirectSale.paid_amount)).scalar() or 0)
    cash_out = float(SupplierPayment.query.filter(
        SupplierPayment.is_void == False,
        *_date_filters(SupplierPayment.date_posted)
    ).with_entities(func.sum(SupplierPayment.amount)).scalar() or 0)

    fbm_drawer_account = Account.query.filter(
        func.lower(func.trim(Account.name)) == 'fbm drawer cash'
    ).first() or Account.query.filter(Account.name.ilike('%fbm drawer cash%')).first()
    fbm_drawer_account_id = fbm_drawer_account.id if fbm_drawer_account else None
    account_cache = {}
    for tx in AccountTransaction.query.filter(
        AccountTransaction.is_void == False,
        AccountTransaction.transaction_type.in_(['Expense', 'Payment', 'Transfer', 'Receipt']),
        *_date_filters(AccountTransaction.date_posted)
    ).all():
        amount = float(tx.amount or 0)
        note_u = (tx.note or '').upper()
        if any(marker in note_u for marker in (
            '[SRC:BOOKING:',
            '[SRC:DIRECTSALE:',
            '[SRC:PAYMENT:',
            '[SRC:SUPPLIERPAYMENT:',
            '[SRC:CLIENTREFUND:',
        )):
            continue
        if tx.transaction_type == 'Transfer' and fbm_drawer_account_id is not None:
            if tx.to_account_id == fbm_drawer_account_id and tx.from_account_id != fbm_drawer_account_id:
                cash_in += amount
            elif tx.from_account_id == fbm_drawer_account_id and tx.to_account_id != fbm_drawer_account_id:
                cash_out += amount
            continue
        if tx.transaction_type == 'Receipt' and tx.to_account_id is not None:
            if tx.to_account_id not in account_cache:
                account_cache[tx.to_account_id] = Account.query.get(tx.to_account_id)
            acc = account_cache.get(tx.to_account_id)
            if acc and (acc.category or '').lower() in ('cash', 'bank'):
                cash_in += amount
            continue
        if tx.transaction_type in ['Expense', 'Payment'] and tx.from_account_id is not None:
            if tx.from_account_id not in account_cache:
                account_cache[tx.from_account_id] = Account.query.get(tx.from_account_id)
            acc = account_cache.get(tx.from_account_id)
            if acc and (acc.category or '').lower() in ('cash', 'bank'):
                cash_out += amount

    return cash_in, cash_out


def _automatic_cash_opening_balance(from_date_dt):
    previous_day = from_date_dt - timedelta(days=1)
    last_physical = CashFlowDifferenceAdjustment.query.filter(
        CashFlowDifferenceAdjustment.adjustment_date < from_date_dt,
        CashFlowDifferenceAdjustment.physical_cash_available.isnot(None)
    ).order_by(CashFlowDifferenceAdjustment.adjustment_date.desc()).first()

    if last_physical:
        start_date = last_physical.adjustment_date + timedelta(days=1)
        opening = float(last_physical.physical_cash_available or 0)
        opening += _cash_flow_net_between(start_date, previous_day)
        opening -= _legacy_adjustments_total(start_date, previous_day)
        return opening

    opening = _cash_flow_net_between(None, previous_day)
    opening -= _legacy_adjustments_total(None, previous_day)
    return opening


def _current_username():
    return current_user.username if current_user and current_user.is_authenticated else None


def _cash_flow_today_opening_override(today_str):
    override = session.get('cash_flow_today_opening_override') or {}
    if override.get('date') != today_str:
        return None
    try:
        return _money_round(override.get('amount', 0))
    except Exception:
        return None


def _cash_flow_fresh_start_cutoff(today_str):
    cutoff = session.get('cash_flow_fresh_start_cutoff') or {}
    if cutoff.get('date') != today_str or not cutoff.get('at'):
        cutoff = {'date': today_str, 'at': pk_now().strftime('%Y-%m-%d %H:%M:%S')}
        session['cash_flow_fresh_start_cutoff'] = cutoff
    try:
        return datetime.strptime(cutoff['at'], '%Y-%m-%d %H:%M:%S')
    except Exception:
        cutoff = {'date': today_str, 'at': pk_now().strftime('%Y-%m-%d %H:%M:%S')}
        session['cash_flow_fresh_start_cutoff'] = cutoff
        return datetime.strptime(cutoff['at'], '%Y-%m-%d %H:%M:%S')


