import os
import secrets
from datetime import timedelta
from pathlib import Path

from flask import Flask

from . import db


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        DB_PATH=os.environ.get("DB_PATH", "./data/workshop.db"),
        APP_PASSWORD=os.environ.get("APP_PASSWORD", ""),
        MAX_CONTENT_LENGTH=100 * 1024 * 1024,
        PERMANENT_SESSION_LIFETIME=timedelta(days=90),
    )
    app.config.update(config or {})
    Path(app.config["DB_PATH"]).parent.mkdir(parents=True, exist_ok=True)
    app.secret_key = os.environ.get("SECRET_KEY") or _cle_persistante(app.config["DB_PATH"])

    db.init_app(app)
    from .views import bp
    app.register_blueprint(bp)
    return app


def _cle_persistante(db_path):
    """Clé générée une fois et gardée à côté de la DB : stable entre workers et redémarrages."""
    f = Path(db_path).parent / ".secret_key"
    if not f.exists():
        f.write_text(secrets.token_hex(32))
    return f.read_text().strip()
