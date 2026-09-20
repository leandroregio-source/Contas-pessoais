"""Categorias padronizadas — as mesmas que o Itaú imprime na fatura.

Manter fatura e recibo no mesmo vocabulário é o que permite comparar
mês a mês sem normalização posterior.
"""
from __future__ import annotations

import re
import unicodedata

CATEGORIAS = (
    "supermercado",
    "restaurante",
    "lazer",
    "saude",
    "viagem",
    "outros",
    "servicos",
    "vestuario",
    "educacao",
    "government",
)

# Rótulos para exibição (o dado guardado é sempre a chave sem acento).
ROTULOS = {
    "supermercado": "Supermercado",
    "restaurante": "Restaurante",
    "lazer": "Lazer",
    "saude": "Saúde",
    "viagem": "Viagem",
    "outros": "Outros",
    "servicos": "Serviços",
    "vestuario": "Vestuário",
    "educacao": "Educação",
    "government": "Government",
}

ORIGENS = ("cartao", "pix", "dinheiro", "debito")
CRIADO_VIA = ("import_fatura", "foto_recibo", "manual")

# Sinônimos que aparecem em faturas/recibos e mapeiam para a lista fixa.
_SINONIMOS = {
    "mercado": "supermercado",
    "supermercados": "supermercado",
    "alimentacao": "supermercado",
    "restaurantes": "restaurante",
    "bar": "restaurante",
    "bares": "restaurante",
    "farmacia": "saude",
    "drogaria": "saude",
    "hospital": "saude",
    "entretenimento": "lazer",
    "diversao": "lazer",
    "transporte": "servicos",
    "posto": "servicos",
    "combustivel": "servicos",
    "assinatura": "servicos",
    "servico": "servicos",
    "roupas": "vestuario",
    "moda": "vestuario",
    "turismo": "viagem",
    "hotel": "viagem",
    "escola": "educacao",
    "curso": "educacao",
    "governo": "government",
    "impostos": "government",
    "imposto": "government",
    "taxas": "government",
}


def sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar_categoria(bruta: str | None) -> str:
    """Converte qualquer grafia para uma das CATEGORIAS. Default: 'outros'."""
    if not bruta:
        return "outros"
    chave = re.sub(r"[^a-z]", "", sem_acento(str(bruta)).lower())
    if chave in CATEGORIAS:
        return chave
    if chave in _SINONIMOS:
        return _SINONIMOS[chave]
    return "outros"


def rotulo(categoria: str) -> str:
    return ROTULOS.get(categoria, categoria.capitalize())
