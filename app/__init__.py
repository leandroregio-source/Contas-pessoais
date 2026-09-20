"""Fábrica da aplicação Flask."""
from __future__ import annotations

import logging

from flask import Flask, jsonify, send_from_directory

from app.config import Config


def create_app(config_override: dict | None = None) -> Flask:
    app = Flask(__name__, static_folder="../static", template_folder="../templates")
    app.config.from_object(Config)
    if config_override:
        app.config.update(config_override)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    from app.api import api
    from app.views import views

    app.register_blueprint(views)
    app.register_blueprint(api)

    # O service worker precisa estar na raiz para controlar todo o escopo do app.
    @app.get("/sw.js")
    def service_worker():
        resposta = send_from_directory(app.static_folder, "sw.js")
        resposta.headers["Cache-Control"] = "no-cache"
        resposta.headers["Content-Type"] = "application/javascript"
        return resposta

    @app.get("/manifest.webmanifest")
    def manifest():
        return send_from_directory(app.static_folder, "manifest.webmanifest")

    @app.after_request
    def cabecalhos_seguranca(resposta):
        resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
        resposta.headers.setdefault("X-Frame-Options", "DENY")
        resposta.headers.setdefault("Referrer-Policy", "same-origin")
        # Dados financeiros: nada de CDN externo, tudo servido localmente.
        resposta.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; "
            "script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; base-uri 'none'; form-action 'self'; "
            "frame-ancestors 'none'",
        )
        return resposta

    @app.errorhandler(413)
    def arquivo_grande(_):
        return jsonify({"erro": "Arquivo grande demais (máx. 12 MB)."}), 413

    @app.errorhandler(404)
    def nao_encontrado(_):
        return jsonify({"erro": "nao_encontrado"}), 404

    @app.errorhandler(500)
    def erro_interno(exc):  # pragma: no cover
        app.logger.exception("Erro interno: %s", exc)
        return jsonify({"erro": "erro_interno"}), 500

    return app
