# AMS Deployment — One File Controls Everything

Everything about *where* the code comes from and *where* it deploys is in
**`config.py`**. After the one-time setup below, your normal work is:

```
edit code  →  git add .  →  git commit -m "..."  →  git push
```

A push to the configured branch automatically deploys to PythonAnywhere,
validates the app, reloads it, and health-checks it. You never have to open
a PythonAnywhere console, `git pull`, install requirements, or reload again.

---

## How it works

```
config.py  ──►  GitHub Actions (.github/workflows/deploy.yml)
                     │  reads non-secret targets from config.py
                     │  POSTs the /git-auto-pull webhook (uses AMS_WEBHOOK_TOKEN)
                     ▼
             PythonAnywhere app (deploy/deployer.py runs inside the live app)
                     │  protect DB + instance/  →  git fetch/hard sync
                     │  →  restore instance/   →  install reqs if changed
                     │  →  import-validate app →  touch WSGI (reload)
                     ▼
             GitHub Actions polls https://<domain>/health
             (reloads via the PythonAnywhere API as a fallback)
```

Secrets live **only** in the environment — never in `config.py`, never in Git.

---

## One-time setup

### A. GitHub Secrets
In the repository → **Settings → Secrets and variables → Actions → New repository secret**, add:

| Secret name | Value |
|---|---|
| `AMS_WEBHOOK_TOKEN` | A long random string you invent (e.g. `openssl rand -hex 24`). This same value goes on PythonAnywhere. |
| `PYTHONANYWHERE_API_TOKEN` | PythonAnywhere → **Account → API token → Create new token**. (Used as a reload fallback.) |

### B. `config.py` values
Open `config.py` and confirm/set the non-secret values to match your server:

```python
GITHUB_OWNER       = "rehmanahmedca-source"
GITHUB_REPOSITORY  = "AMSCOPY9"
GITHUB_BRANCH      = "main"

PYTHONANYWHERE_USERNAME = "tempservofbm"
PYTHONANYWHERE_DOMAIN   = "tempservofbm.pythonanywhere.com"
```
The project path, virtualenv path, WSGI path, API endpoint, reload endpoint
and health URL are all **derived** from those — change the username/domain
and everything follows.

### C. PythonAnywhere (manual, once)

1. **Open a Bash console** and clone the repo into your home folder:
   ```bash
   cd ~
   git clone https://github.com/rehmanahmedca-source/AMSCOPY9.git AMSCOPY9
   cd AMSCOPY9
   ```
2. **Create the virtual environment** (Python 3.11):
   ```bash
   mkvirtualenv --python=/usr/bin/python3.11 ams-venv
   pip install -r requirements.txt
   ```
   (Virtualenv path used by config: `~/.virtualenvs/ams-venv`.)
3. **Set the webhook secret as an environment variable** so the deployed
   app can authenticate GitHub. Add it to the WSGI file (step 5) **and** to a
   file the bash console sources. The most reliable place for the web app is
   the WSGI file — see step 5.
4. **Web app → Add a new web app → Manual configuration → Python 3.11.**
5. Edit the **WSGI file** (the `Code` section links to it, e.g.
   `/var/www/tempservofbm_pythonanywhere_com_wsgi.py`) so it contains:
   ```python
   import os, sys
   path = "/home/tempservofbm/AMSCOPY9"
   if path not in sys.path:
       sys.path.insert(0, path)

   # Secret for the auto-deploy webhook (do NOT commit this anywhere)
   os.environ["AMS_WEBHOOK_TOKEN"] = "PASTE_THE_SAME_LONG_RANDOM_TOKEN"
   # Use the virtualenv
   os.environ["VIRTUAL_ENV"] = "/home/tempservofbm/.virtualenvs/ams-venv"

   from wsgi import app as application  # noqa
   ```
   Also set the **Virtualenv path** on the Web tab to
   `/home/tempservofbm/.virtualenvs/ams-venv`.
6. **Reload the web app.** Confirm it responds:
   `https://tempservofbm.pythonanywhere.com/health` should show
   `{"status":"healthy",...}`.
7. **Authorize outbound API/network** if needed: on PythonAnywhere the free
   tier can reach the public `/health` URL from GitHub Actions (Actions runs
   on GitHub, not PythonAnywhere, so no PA network restrictions apply to it).

### D. Enable the webhook
GitHub Actions calls the webhook directly (no GitHub webhook registration is
required). If you *also* want GitHub to nudge the server, you can add a
repository Webhook (Settings → Webhooks → Add):
- Payload URL: `https://<your-domain>/git-auto-pull?token=YOUR_TOKEN`
- Content type: application/json
- Events: **Just the push event**

This is optional — the included GitHub Action already triggers the deploy.

---

## Normal operation

```bash
git add .
git commit -m "your change"
git push
```

Watch it live: GitHub repo → **Actions** tab. Each run shows:
config loaded → webhook triggered → server sync/validate/reload → health pass.

The on-server stages are logged in `deployment.log` on PythonAnywhere.

---

## Safety

- **Live data is never overwritten.** Before any `git reset`, the deployer
  snapshots `instance/` (the SQLite DB, wal/shm, secret key, logs) and copies
  it back after the sync. Code and runtime data are fully separated.
- **A pre-deploy DB backup** is written to `instance/backups/` every deploy
  (git-ignored).
- **Stops on failure.** If fetch, requirements, app import, or validation
  fail, the reload is not performed and the failure is reported — a working
  app keeps running.
- **Migrations are automatic and safe:** importing the app applies any
  missing schema columns (`db.create_all` + column reconciliation). The
  deployer validates this import before reload.

---

## Rollback

Code rollback and database rollback are deliberately separate.

**Roll code back** to the commit just before the last deploy:
```bash
# on the server (a PythonAnywhere Bash console), from the project folder:
python deploy/deploy.py --rollback
```
To roll to a specific commit:
```bash
python deploy/deploy.py --rollback --to-commit <commit-sha>
```
The previous/last deployed commits are tracked in `.deploy_state.json`.

**Database rollback** is a manual decision (restoring an older snapshot loses
newer transactions). Snapshots are in `instance/backups/`. Stop the web app,
copy the chosen `ahmed_cement_v44_fresh.<timestamp>.db` over
`instance/ahmed_cement_v44_fresh.db`, and reload.

---

## Local / dry-run checks

```bash
python config.py                # print the deployment control panel + validity
python deploy/deploy.py --show  # same, via the CLI
python deploy/deploy.py --check # require the webhook secret env var too
python deploy/deploy.py --dry-run
python deploy/deploy.py --health   # probe the configured health URL
```

---

## Changing to a different repository or server

Only edit `config.py` (or set `AMS_*` env overrides) — no other file:

```python
GITHUB_OWNER      = "newname"
GITHUB_REPOSITORY = "new-project"
GITHUB_BRANCH     = "main"

PYTHONANYWHERE_USERNAME = "newuser"
PYTHONANYWHERE_DOMAIN   = "newuser.pythonanywhere.com"
```

The derived values (project path, venv path, WSGI path, API reload endpoint,
health URL) all recompute automatically. On a new server, repeat only the
one-time PythonAnywhere setup (section C).

| Want to change | Edit |
|---|---|
| GitHub repository | `GITHUB_OWNER`, `GITHUB_REPOSITORY` |
| Production branch | `GITHUB_BRANCH` |
| PA account / domain | `PYTHONANYWHERE_USERNAME`, `PYTHONANYWHERE_DOMAIN` |
| Project directory | `PYTHONANYWHERE_PROJECT_PATH` (or `AMS_PA_PROJECT_PATH`) |
| Virtual environment | `PYTHONANYWHERE_VENV_PATH` (or `AMS_PA_VENV_PATH`) |
| WSGI file | `PYTHONANYWHERE_WSGI_PATH` |
| Toggle a stage | the `DEPLOYMENT CONFIGURATION` switches in `config.py` |
