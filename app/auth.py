"""Autenticação por PIN — single-user, como pede a especificação.

Não é sistema de login: é uma trava para o caso de o celular ficar aberto.
A proteção real dos dados é o Supabase com RLS negando anon/authenticated e a
service_role key nunca saindo do servidor.
"""
from __future__ import annotations

import hmac
import time
from functools import wraps

from flask import current_app, jsonify, redirect, request, session, url_for

_JANELA_S = 300          # janela de contagem de tentativas
_MAX_TENTATIVAS = 5
_tentativas: dict[str, list[float]] = {}


def pin_configurado() -> bool:
    return bool(current_app.config.get("APP_PIN"))


def esta_logado() -> bool:
    if not pin_configurado():
        return True          # sem PIN definido, app roda aberto (dev)
    return bool(session.get("autenticado"))


def _origem() -> str:
    return request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0]


def bloqueado() -> bool:
    agora = time.time()
    recentes = [t for t in _tentativas.get(_origem(), []) if agora - t < _JANELA_S]
    _tentativas[_origem()] = recentes
    return len(recentes) >= _MAX_TENTATIVAS


def registrar_falha() -> None:
    _tentativas.setdefault(_origem(), []).append(time.time())


def conferir_pin(pin: str) -> bool:
    """Comparação em tempo constante — evita descobrir o PIN por timing."""
    esperado = current_app.config.get("APP_PIN", "")
    if not esperado:
        return True
    ok = hmac.compare_digest(str(pin or "").strip(), esperado)
    if ok:
        _tentativas.pop(_origem(), None)
        session.permanent = True
        session["autenticado"] = True
    else:
        registrar_falha()
    return ok


def sair() -> None:
    session.clear()


def exige_login(fn):
    """Protege rotas de página (redireciona) e de API (401 em JSON)."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if esta_logado():
            return fn(*args, **kwargs)
        if request.path.startswith("/api/"):
            return jsonify({"erro": "nao_autenticado"}), 401
        return redirect(url_for("views.login", proximo=request.path))

    return wrapper
