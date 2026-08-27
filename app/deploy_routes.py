"""Public deployment routes registered on the Flask app.

* ``/health``        — unauthenticated liveness/readiness probe used by the
                       deploy pipeline (and by PythonAnywhere / GitHub
                       Actions) to confirm the app imported and the DB is
                       reachable. No business data is exposed.
* ``/git-auto-pull`` — GitHub push webhook that triggers the config-driven
                       automatic deployer (deploy.deployer).

Both are registered in the app factory so they work regardless of whether
the process is started via ``wsgi.py`` (PythonAnywhere) or ``main.py``
(local). All deployment settings come from ``config.py``.
"""
from __future__ import annotations

import logging
import threading

from flask import jsonify, request

logger = logging.getLogger("AMS-Deploy")


def register_deploy_routes(app):
    from config import get_config
    from deploy import deployer

    cfg = get_config()
    gh = cfg["github"]
    branch_ref = f"refs/heads/{gh['branch']}"

    @app.route("/health")
    def health():
        """Lightweight public health check (no secrets, no sensitive data)."""
        status = "healthy"
        db_ok = True
        try:
            from models import db
            from sqlalchemy import text

            db.session.execute(text("SELECT 1")).scalar()
        except Exception as exc:  # pragma: no cover - environmental
            db_ok = False
            status = "degraded"
            logger.warning("Health DB probe failed: %s", exc)
        try:
            from config import get_config as _gc
            import subprocess

            head = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            commit = head.stdout.strip() if head.returncode == 0 else None
        except Exception:
            commit = None
        return (
            jsonify(
                {
                    "status": status if db_ok else "unhealthy",
                    "database": "ok" if db_ok else "error",
                    "app": cfg["app"]["name"],
                    "branch": gh["branch"],
                    "commit": commit,
                }
            ),
            200 if db_ok else 503,
        )

    @app.route("/git-auto-pull", methods=["GET", "POST"])
    def git_auto_pull():
        token = (
            request.args.get("token", "", type=str).strip()
            or (request.headers.get("X-Deploy-Token") or "").strip()
        )
        expected = deployer.webhook_token()
        if request.method == "GET":
            # A browser/monitor probe: report online without revealing whether
            # the deploy secret is present (no deployment can be triggered by
            # GET, so this is safe to expose).
            return jsonify(
                {"success": True, "service": "AMS Git Auto Pull", "status": "online"}
            ), 200
        # POST actually triggers a deploy and must be authenticated.
        if not expected:
            # No token configured on the server -> refuse rather than deploy.
            logger.error("Webhook called but %s is not set.", cfg["secrets"]["webhook_token_env"])
            return jsonify({"success": False, "message": "Deploy token not configured"}), 503
        if token != expected:
            logger.warning("Unauthorized deployment request.")
            return jsonify({"success": False, "message": "Unauthorized"}), 403

        event = request.headers.get("X-GitHub-Event", "")
        if event and event != "push":
            return jsonify({"success": True, "message": "Event ignored"}), 200

        payload = request.get_json(silent=True) or {}
        ref = payload.get("ref", "")
        # Only deploy pushes to the configured branch.
        if ref and ref != branch_ref:
            return jsonify({"success": True, "message": "Branch ignored"}), 200

        if deployer._DEPLOY_LOCK.locked():
            return jsonify({"success": True, "message": "Deployment already running"}), 202

        def _run():
            try:
                deployer.deploy()
            except Exception:  # pragma: no cover - defensive
                logger.exception("Background deploy crashed.")

        threading.Thread(target=_run, daemon=True).start()
        return jsonify({"success": True, "message": "Deployment started"}), 202
