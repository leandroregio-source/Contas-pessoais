"""Ponto de entrada local: python run.py"""
from __future__ import annotations

import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    porta = int(os.getenv("PORT", "5000"))
    # host 0.0.0.0 para abrir no celular pela rede local.
    app.run(host="0.0.0.0", port=porta, debug=os.getenv("FLASK_DEBUG") == "1")
