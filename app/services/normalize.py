"""Validação e normalização de um gasto vindo do cliente.

Tudo que entra por HTTP passa por aqui antes de tocar o banco: o front é um
PWA no celular do dono, mas isso não é razão para confiar no payload.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import date, datetime

from app.categorias import CRIADO_VIA, ORIGENS, normalizar_categoria

MAX_ESTAB = 120
MAX_OBS = 500


class DadoInvalido(ValueError):
    pass


def _data(valor) -> str:
    texto = str(valor or "").strip()
    if not texto:
        return date.today().isoformat()
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(texto, formato).date().isoformat()
        except ValueError:
            continue
    raise DadoInvalido(f"Data inválida: {valor!r}")


def _valor(bruto) -> float:
    if isinstance(bruto, (int, float)):
        numero = float(bruto)
    else:
        texto = re.sub(r"[^\d,.-]", "", str(bruto or ""))
        if texto.count(",") == 1 and (texto.rfind(",") > texto.rfind(".")):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
        try:
            numero = float(texto)
        except ValueError as exc:
            raise DadoInvalido(f"Valor inválido: {bruto!r}") from exc
    if numero == 0:
        raise DadoInvalido("O valor não pode ser zero.")
    if abs(numero) > 1_000_000:
        raise DadoInvalido("Valor fora da faixa esperada.")
    return round(numero, 2)


def _texto(bruto, limite: int) -> str:
    return re.sub(r"\s+", " ", str(bruto or "")).strip()[:limite]


def normalizar_gasto(payload: dict, criado_via: str = "manual") -> dict:
    estabelecimento = _texto(payload.get("estabelecimento"), MAX_ESTAB)
    if not estabelecimento:
        raise DadoInvalido("Informe o estabelecimento.")

    origem = str(payload.get("origem") or "dinheiro").strip().lower()
    if origem not in ORIGENS:
        origem = "dinheiro"

    via = criado_via if criado_via in CRIADO_VIA else "manual"
    data_iso = _data(payload.get("data"))
    valor = _valor(payload.get("valor"))

    tem_juros = bool(payload.get("tem_juros"))
    valor_juros = None
    if tem_juros and payload.get("valor_juros") not in (None, "", 0):
        valor_juros = abs(_valor(payload.get("valor_juros")))
        if valor_juros > abs(valor):
            raise DadoInvalido("O juros não pode ser maior que o valor do gasto.")

    gasto = {
        "id": str(uuid.uuid4()),
        "data": data_iso,
        "estabelecimento": estabelecimento,
        "valor": valor,
        "categoria": normalizar_categoria(payload.get("categoria")),
        "origem": origem,
        "fatura_referencia": _texto(payload.get("fatura_referencia"), 7) or None,
        "tem_juros": tem_juros,
        "valor_juros": valor_juros,
        "criado_via": via,
        "observacoes": _texto(payload.get("observacoes"), MAX_OBS) or None,
        "parcela_atual": _inteiro(payload.get("parcela_atual")),
        "parcela_total": _inteiro(payload.get("parcela_total")),
        "moeda_origem": None,
        "valor_origem": None,
        "cartao": _texto(payload.get("cartao"), 40) or None,
    }
    gasto["hash_dedupe"] = hashlib.sha256(
        f"{via}|{data_iso}|{estabelecimento.lower()}|{valor:.2f}|{gasto['id']}".encode()
    ).hexdigest()[:32]
    return gasto


def _inteiro(bruto) -> int | None:
    if bruto in (None, ""):
        return None
    try:
        numero = int(bruto)
    except (TypeError, ValueError):
        return None
    return numero if 0 < numero <= 99 else None


def normalizar_edicao(payload: dict) -> dict:
    """Só os campos presentes — PATCH parcial."""
    campos: dict = {}
    if "data" in payload:
        campos["data"] = _data(payload["data"])
    if "estabelecimento" in payload:
        estab = _texto(payload["estabelecimento"], MAX_ESTAB)
        if not estab:
            raise DadoInvalido("Informe o estabelecimento.")
        campos["estabelecimento"] = estab
    if "valor" in payload:
        campos["valor"] = _valor(payload["valor"])
    if "categoria" in payload:
        campos["categoria"] = normalizar_categoria(payload["categoria"])
    if "origem" in payload:
        origem = str(payload["origem"]).strip().lower()
        campos["origem"] = origem if origem in ORIGENS else "dinheiro"
    if "observacoes" in payload:
        campos["observacoes"] = _texto(payload["observacoes"], MAX_OBS) or None
    if "tem_juros" in payload:
        campos["tem_juros"] = bool(payload["tem_juros"])
    if "valor_juros" in payload:
        bruto = payload["valor_juros"]
        campos["valor_juros"] = None if bruto in (None, "") else abs(_valor(bruto))
    if "parcela_atual" in payload:
        campos["parcela_atual"] = _inteiro(payload["parcela_atual"])
    if "parcela_total" in payload:
        campos["parcela_total"] = _inteiro(payload["parcela_total"])
    if "cartao" in payload:
        campos["cartao"] = _texto(payload["cartao"], 40) or None
    if not campos:
        raise DadoInvalido("Nada para atualizar.")
    return campos
