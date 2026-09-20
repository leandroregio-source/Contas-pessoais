import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def cliente():
    """App com SQLite temporário e sem PIN — isolado por teste."""
    fd, caminho = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    os.unlink(caminho)

    from app.config import Config
    from app.repo import reset_repo

    Config.SQLITE_PATH = caminho
    Config.SUPABASE_URL = ""
    Config.SUPABASE_SERVICE_KEY = ""
    reset_repo()

    from app import create_app

    app = create_app({"APP_PIN": "", "SQLITE_PATH": caminho, "TESTING": True})
    yield app.test_client()

    reset_repo()
    if os.path.exists(caminho):
        os.unlink(caminho)
