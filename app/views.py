"""Rotas de página do PWA."""
from __future__ import annotations

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for

from app.auth import bloqueado, conferir_pin, esta_logado, exige_login, pin_configurado, sair

views = Blueprint("views", __name__)


@views.get("/")
@exige_login
def app_shell():
    return render_template("app.html")


@views.route("/login", methods=["GET", "POST"])
def login():
    proximo = request.values.get("proximo") or url_for("views.app_shell")
    if esta_logado():
        return redirect(proximo)

    erro = None
    if request.method == "POST":
        if bloqueado():
            erro = "Muitas tentativas. Aguarde alguns minutos."
        elif conferir_pin(request.form.get("pin", "")):
            return redirect(proximo)
        else:
            erro = "PIN incorreto."
    return render_template("login.html", erro=erro, proximo=proximo), (401 if erro else 200)


@views.post("/sair")
def logout():
    sair()
    return redirect(url_for("views.login"))
