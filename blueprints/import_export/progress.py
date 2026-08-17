"""import helpers."""
from ._common import *  # noqa

def _get_data_upgrade_queue_dir():
    queue_dir = current_app.config.get(
        'DATA_UPGRADE_QUEUE_DIR',
        os.path.join(current_app.instance_path, 'data_upgrade_queue')
    )
    os.makedirs(queue_dir, exist_ok=True)
    processed_dir = os.path.join(queue_dir, 'processed')
    os.makedirs(processed_dir, exist_ok=True)
    return queue_dir, processed_dir


def _load_deploy_history(history_path):
    if not os.path.exists(history_path):
        return []
    try:
        with open(history_path, 'r', encoding='utf-8') as f:
            return json.load(f) or []
    except Exception:
        return []


def _save_deploy_history(history_path, items):
    os.makedirs(os.path.dirname(history_path), exist_ok=True)
    with open(history_path, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=True, indent=2)


def _append_deploy_history(history_path, entry):
    items = _load_deploy_history(history_path)
    items.insert(0, entry)
    _save_deploy_history(history_path, items)


def _set_deploy_progress(job_id, **fields):
    with _DEPLOY_PROGRESS_LOCK:
        state = _DEPLOY_PROGRESS.get(job_id, {})
        state.update(fields)
        _DEPLOY_PROGRESS[job_id] = state


def _get_deploy_progress(job_id):
    with _DEPLOY_PROGRESS_LOCK:
        state = _DEPLOY_PROGRESS.get(job_id)
        return dict(state) if state else None


def _set_master_import_progress(job_id, **fields):
    with _MASTER_IMPORT_PROGRESS_LOCK:
        state = _MASTER_IMPORT_PROGRESS.get(job_id, {})
        state.update(fields)
        _MASTER_IMPORT_PROGRESS[job_id] = state


def _get_master_import_progress(job_id):
    with _MASTER_IMPORT_PROGRESS_LOCK:
        state = _MASTER_IMPORT_PROGRESS.get(job_id)
        return dict(state) if state else None


@import_export_bp.route('/full_raw_import_history_export')
@login_required
def full_raw_import_history_export():
    if current_user.role not in ['admin', 'root']:
        return "Forbidden", 403
    reports = _list_full_raw_reports()
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            'name', 'created_at', 'row_count', 'scope', 'mode', 'tenant_name',
            'inserted', 'skipped', 'tables', 'source_file'
        ]
    )
    writer.writeheader()
    writer.writerows(reports)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={_download_filename('IMPORTREPORTHISTORY', 'csv')}"}
    )


@import_export_bp.route('/master/import/status/<job_id>', methods=['GET'])
@login_required
def master_import_status(job_id):
    state = _get_master_import_progress(job_id)
    if not state:
        return jsonify({'error': 'Unknown job id'}), 404

    owner = state.get('user')
    if owner and owner != getattr(current_user, 'username', None) and getattr(current_user, 'role', None) not in ['admin', 'root']:
        return jsonify({'error': 'Forbidden'}), 403
    return jsonify(state)


