"""Extração por IA (API da Anthropic).

Usada em dois pontos, e só neles — a fatura do Itaú é texto estruturado e sai
por regex, sem custo de API:

1. Foto de nota/recibo: visão + saída em JSON validado por schema.
2. Fallback de categoria: quando a fatura não imprimiu a categoria de alguns
   lançamentos, todos vão numa ÚNICA chamada em lote (não uma por linha).
"""
from __future__ import annotations

import base64
import json
import logging

from app.categorias import CATEGORIAS, normalizar_categoria
from app.config import Config

log = logging.getLogger(__name__)

MIMES_ACEITOS = {
    "image/jpeg": "image/jpeg",
    "image/jpg": "image/jpeg",
    "image/png": "image/png",
    "image/webp": "image/webp",
    "image/gif": "image/gif",
}


class ExtracaoIndisponivel(RuntimeError):
    """ANTHROPIC_API_KEY ausente ou SDK não instalado."""


def _cliente():
    if not Config.tem_claude():
        raise ExtracaoIndisponivel(
            "ANTHROPIC_API_KEY não configurada — a leitura de recibo por foto "
            "precisa dela. O lançamento manual continua funcionando."
        )
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - ambiente sem a lib
        raise ExtracaoIndisponivel("Pacote 'anthropic' não instalado.") from exc
    return anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)


def _texto_da_resposta(resposta) -> str:
    return "".join(b.text for b in resposta.content if b.type == "text")


def _chamar_json(client, *, conteudo, schema, system, effort="medium", max_tokens=8000):
    """Chama a API pedindo JSON conforme `schema`.

    Se o SDK instalado for antigo e não conhecer `output_config`, refaz a
    chamada pedindo JSON no prompt — o app não pode quebrar por causa da
    versão de uma lib.
    """
    base = dict(
        model=Config.ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": conteudo}],
    )
    try:
        resposta = client.messages.create(
            **base,
            output_config={
                "effort": effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        )
        return json.loads(_texto_da_resposta(resposta))
    except TypeError:
        log.warning("SDK anthropic sem output_config; usando fallback por prompt.")
    except Exception as exc:  # noqa: BLE001 - erro de API vira mensagem de tela
        if "output_config" not in str(exc):
            raise
        log.warning("output_config recusado pela API; usando fallback por prompt.")

    resposta = client.messages.create(
        **{
            **base,
            "system": system + "\n\nResponda SOMENTE com JSON válido, sem cercas de código.",
        }
    )
    return _json_do_texto(_texto_da_resposta(resposta))


def _json_do_texto(texto: str):
    texto = texto.strip()
    if texto.startswith("```"):
        texto = texto.strip("`")
        texto = texto.split("\n", 1)[1] if "\n" in texto else texto
    inicio = min(
        (i for i in (texto.find("{"), texto.find("[")) if i != -1), default=-1
    )
    if inicio == -1:
        raise ValueError(f"Resposta sem JSON: {texto[:200]}")
    fim = max(texto.rfind("}"), texto.rfind("]"))
    return json.loads(texto[inicio : fim + 1])


# --------------------------------------------------------------------------
# 1. Foto de recibo
# --------------------------------------------------------------------------

_SCHEMA_RECIBO = {
    "type": "object",
    "properties": {
        "estabelecimento": {"type": "string"},
        "valor": {"type": "number"},
        "data": {
            "type": "string",
            "description": "Data da compra no formato AAAA-MM-DD. Vazio se ilegível.",
        },
        "categoria_sugerida": {"type": "string", "enum": list(CATEGORIAS)},
        "origem_sugerida": {
            "type": "string",
            "enum": ["pix", "dinheiro", "debito", "cartao"],
        },
        "itens": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "descricao": {"type": "string"},
                    "valor": {"type": "number"},
                },
                "required": ["descricao", "valor"],
                "additionalProperties": False,
            },
        },
        "confianca": {
            "type": "string",
            "enum": ["alta", "media", "baixa"],
            "description": "Quão legível estava o comprovante.",
        },
        "observacao": {"type": "string"},
    },
    "required": [
        "estabelecimento", "valor", "data", "categoria_sugerida",
        "origem_sugerida", "itens", "confianca", "observacao",
    ],
    "additionalProperties": False,
}

_SYSTEM_RECIBO = f"""Você lê fotos de notas fiscais, cupons e comprovantes brasileiros \
e extrai os dados do gasto.

Regras:
- `valor` é o TOTAL PAGO, não o subtotal e não o valor de um item isolado. \
Em cupom fiscal, use "VALOR TOTAL R$" / "TOTAL A PAGAR". Desconsidere \
"troco", "dinheiro recebido" e "valor recebido".
- `data` no formato AAAA-MM-DD. Se a data não estiver legível, devolva "".
- `categoria_sugerida` deve ser exatamente uma de: {", ".join(CATEGORIAS)}.
  Use "servicos" para transporte, combustível, assinaturas e contas; \
"government" para impostos e taxas públicas.
- `origem_sugerida`: "pix" se houver comprovante Pix/QR, "debito" se a forma \
de pagamento indicar cartão de débito, "cartao" para crédito, "dinheiro" caso \
contrário ou indefinido.
- `itens` lista os produtos com valor unitário quando o cupom discrimina. \
Lista vazia se não der.
- `confianca` = "baixa" quando a imagem estiver borrada, cortada ou o total for \
incerto. Prefira admitir baixa confiança a inventar número.
- Nunca invente valor, data ou nome. O usuário confere tudo antes de salvar."""


def extrair_recibo(imagem_bytes: bytes, mime: str) -> dict:
    """Lê a foto de um recibo e devolve os campos do gasto (para conferência)."""
    media_type = MIMES_ACEITOS.get((mime or "").lower())
    if not media_type:
        raise ValueError(f"Formato de imagem não suportado: {mime}")

    client = _cliente()
    dados = _chamar_json(
        client,
        conteudo=[
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.standard_b64encode(imagem_bytes).decode("utf-8"),
                },
            },
            {
                "type": "text",
                "text": "Extraia os dados deste comprovante conforme as regras.",
            },
        ],
        schema=_SCHEMA_RECIBO,
        system=_SYSTEM_RECIBO,
        effort="medium",
    )

    dados["categoria_sugerida"] = normalizar_categoria(dados.get("categoria_sugerida"))
    try:
        dados["valor"] = round(abs(float(dados.get("valor") or 0)), 2)
    except (TypeError, ValueError):
        dados["valor"] = 0.0
    if dados.get("origem_sugerida") not in ("pix", "dinheiro", "debito", "cartao"):
        dados["origem_sugerida"] = "dinheiro"
    return dados


# --------------------------------------------------------------------------
# 2. Fallback de categoria (lote)
# --------------------------------------------------------------------------

_SCHEMA_CATEGORIAS = {
    "type": "object",
    "properties": {
        "classificacoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "indice": {"type": "integer"},
                    "categoria": {"type": "string", "enum": list(CATEGORIAS)},
                },
                "required": ["indice", "categoria"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["classificacoes"],
    "additionalProperties": False,
}


def classificar_estabelecimentos(nomes: list[str]) -> dict[int, str]:
    """Classifica em LOTE os estabelecimentos sem categoria impressa.

    Uma chamada para a fatura inteira. Devolve {índice: categoria}; índices
    ausentes ficam como estavam.
    """
    if not nomes:
        return {}
    client = _cliente()
    listagem = "\n".join(f"{i}. {nome}" for i, nome in enumerate(nomes))
    dados = _chamar_json(
        client,
        conteudo=[
            {
                "type": "text",
                "text": (
                    "Classifique cada estabelecimento de fatura de cartão "
                    "brasileira na categoria correspondente. Devolva um item "
                    "por índice.\n\n" + listagem
                ),
            }
        ],
        schema=_SCHEMA_CATEGORIAS,
        system=(
            "Você classifica estabelecimentos de fatura de cartão brasileira em "
            f"categorias fixas: {', '.join(CATEGORIAS)}.\n"
            "Use 'servicos' para transporte, combustível, assinaturas digitais, "
            "telefonia e contas; 'government' para impostos, taxas e órgãos "
            "públicos; 'outros' quando o nome não permitir concluir nada. "
            "Não invente: na dúvida, 'outros'."
        ),
        effort="low",
        max_tokens=4000,
    )

    saida: dict[int, str] = {}
    for item in dados.get("classificacoes", []):
        try:
            idx = int(item["indice"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= idx < len(nomes):
            saida[idx] = normalizar_categoria(item.get("categoria"))
    return saida
