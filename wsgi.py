import os
import logging
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# PythonAnywhere may not put the project directory on sys.path when it loads
# the WSGI file.  Add it explicitly so imports work regardless of the working
# directory configured for the web app.
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

DB_PATH = os.path.join(BASE_DIR, "instance", "ahmed_cement.db")
# The application factory reads APP_DB_PATH. Keep the live database beside
# this project and never substitute a backup database file.
os.environ.setdefault("APP_DB_PATH", DB_PATH)
# A missing live DB is a valid first-run state.
os.environ.setdefault("ALLOW_EMPTY_DB", "1")
# The web process must not create scheduled backup/database copies.
os.environ["BACKUP_EMBEDDED_SCHEDULER"] = "0"
logging.basicConfig(level=logging.INFO)

from app import create_app

app = create_app()
application = app
