"""API JSON do app. Tudo sob /api, tudo atrás do PIN."""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from app.auth import exige_login
from app.categorias import CATEGORIAS, ORIGENS, rotulo
from app.config import Config
from app.repo import get_repo
from app.services import analytics as an
from app.services.claude_extract import (
    ExtracaoIndisponivel,
    classificar_estabelecimentos,
    extrair_recibo,
)
from app.services.itau_fatura import parse_fatura
from app.services.normalize import DadoInvalido, normalizar_edicao, normalizar_gasto
from app.services.pdf_text import PDFIlegivel, extrair_texto

log = logging.getLogger(__name__)
api = Blueprint("api", __name__, url_prefix="/api")

# Janela padrão de análise: 13 meses cobre "mesmo mês do ano passado".
MESES_JANELA = 13


@api.errorhandler(DadoInvalido)
def _dado_invalido(exc):
    return jsonify({"erro": str(exc)}), 400


def _janela(mes: str) -> tuple[str, str]:
    meses = an.ultimos_meses(mes, MESES_JANELA)
    return f"{meses[0]}-01", f"{mes}-31"


def _gastos_da_janela(mes: str) -> list[dict]:
    desde, ate = _janela(mes)
    return get_repo().listar_gastos(desde=desde, ate=ate)


def _mes_pedido() -> str:
    mes = (request.args.get("mes") or "").strip()
    return mes if len(mes) == 7 and mes[4] == "-" else an.mes_atual()


# --------------------------------------------------------------------------
# Metadados
# --------------------------------------------------------------------------

@api.get("/meta")
@exige_login
def meta():
    return jsonify(
        {
            "categorias": [{"valor": c, "rotulo": rotulo(c)} for c in CATEGORIAS],
            "origens": list(ORIGENS),
            "mes_atual": an.mes_atual(),
            "backend": "supabase" if Config.usa_supabase() else "sqlite",
            "ia_disponivel": Config.tem_claude(),
            "cartoes": [
                {"chave": l["chave"], "nome": l["nome"]}
                for l in get_repo().listar_linhas_orcamento()
                if l["secao"] == "cartao" and l.get("ativo", True)
            ],
        }
    )


@api.get("/saude")
def saude():
    return jsonify({"ok": get_repo().ping()})


# --------------------------------------------------------------------------
# Dashboard / análises
# --------------------------------------------------------------------------

@api.get("/dashboard")
@exige_login
def dashboard():
    mes = _mes_pedido()
    gastos = _gastos_da_janela(mes)
    resumo = an.resumo_mensal(gastos, mes)
    resumo["comparativo"] = an.comparativo_categorias(gastos, mes)
    return jsonify(resumo)


@api.get("/insights")
@exige_login
def insights():
    mes = _mes_pedido()
    gastos = _gastos_da_janela(mes)
    repo = get_repo()
    comprometido = repo.listar_parcelas_futuras()
    return jsonify(
        {
            "mes": mes,
            "sugestoes": an.gerar_sugestoes(gastos, mes),
            "recorrentes": an.detectar_recorrentes(gastos, referencia=mes),
            "juros": an.juros_do_periodo(gastos),
            "ranking_crescimento": an.ranking_crescimento(gastos, mes),
            "serie": [
                {"mes": m, "total": an.total_por_mes(gastos).get(m, 0.0)}
                for m in an.ultimos_meses(mes, 12)
            ],
            "parcelas_futuras": comprometido,
            "total_comprometido": round(
                sum(float(p.get("valor_parcela") or 0) for p in comprometido), 2
            ),
        }
    )


# --------------------------------------------------------------------------
# CRUD de gastos
# --------------------------------------------------------------------------

@api.get("/gastos")
@exige_login
def listar_gastos():
    try:
        limite = min(int(request.args.get("limite", 500)), 5000)
    except ValueError:
        limite = 500
    gastos = get_repo().listar_gastos(
        desde=request.args.get("desde") or None,
        ate=request.args.get("ate") or None,
        categoria=request.args.get("categoria") or None,
        origem=request.args.get("origem") or None,
        busca=(request.args.get("busca") or "").strip() or None,
        limite=limite,
    )
    return jsonify(
        {
            "gastos": gastos,
            "total": round(sum(float(g.get("valor") or 0) for g in gastos), 2),
            "quantidade": len(gastos),
        }
    )


@api.post("/gastos")
@exige_login
def criar_gasto():
    payload = request.get_json(silent=True) or {}
    gasto = normalizar_gasto(payload, criado_via=payload.get("criado_via", "manual"))
    get_repo().inserir_gastos([gasto])
    return jsonify(gasto), 201


@api.patch("/gastos/<gasto_id>")
@exige_login
def editar_gasto(gasto_id: str):
    campos = normalizar_edicao(request.get_json(silent=True) or {})
    atualizado = get_repo().atualizar_gasto(gasto_id, campos)
    if not atualizado:
        return jsonify({"erro": "nao_encontrado"}), 404
    return jsonify(atualizado)


@api.delete("/gastos/<gasto_id>")
@exige_login
def remover_gasto(gasto_id: str):
    if not get_repo().remover_gasto(gasto_id):
        return jsonify({"erro": "nao_encontrado"}), 404
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# Foto de recibo
# --------------------------------------------------------------------------

@api.post("/recibo/extrair")
@exige_login
def recibo_extrair():
    """Lê a foto e DEVOLVE para conferência. Não salva nada aqui.

    Salvar direto esconderia erro de leitura — o usuário confirma na tela.
    """
    arquivo = request.files.get("foto")
    if not arquivo or not arquivo.filename:
        return jsonify({"erro": "Envie uma foto no campo 'foto'."}), 400
    dados_imagem = arquivo.read()
    if not dados_imagem:
        return jsonify({"erro": "Arquivo vazio."}), 400
    try:
        extraido = extrair_recibo(dados_imagem, arquivo.mimetype or "image/jpeg")
    except ExtracaoIndisponivel as exc:
        return jsonify({"erro": str(exc), "codigo": "ia_indisponivel"}), 503
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        log.exception("Falha ao extrair recibo")
        return jsonify({"erro": f"Não consegui ler a imagem: {exc}"}), 502
    return jsonify(extraido)


# --------------------------------------------------------------------------
# Importação da fatura
# --------------------------------------------------------------------------

@api.post("/fatura/analisar")
@exige_login
def fatura_analisar():
    """Extrai a prévia da fatura. Nada é salvo antes da confirmação."""
    arquivo = request.files.get("pdf")
    if not arquivo or not arquivo.filename:
        return jsonify({"erro": "Envie o PDF no campo 'pdf'."}), 400

    referencia = (request.form.get("referencia") or "").strip() or None
    usar_ia = (request.form.get("usar_ia") or "1") not in ("0", "false", "nao")

    try:
        texto = extrair_texto(arquivo.read(), senha=request.form.get("senha"))
    except PDFIlegivel as exc:
        return jsonify({"erro": str(exc)}), 400

    fatura = parse_fatura(texto, referencia=referencia)

    # A fatura já traz a categoria impressa na maioria das linhas. A IA só
    # entra no que sobrou — e numa chamada só para a fatura inteira.
    incertos = [i for i, l in enumerate(fatura.lancamentos) if l.categoria_incerta]
    classificados_por_ia = 0
    aviso_ia = None
    if incertos and usar_ia and Config.tem_claude():
        try:
            sugestoes = classificar_estabelecimentos(
                [fatura.lancamentos[i].estabelecimento for i in incertos]
            )
            for pos, categoria in sugestoes.items():
                fatura.lancamentos[incertos[pos]].categoria = categoria
            classificados_por_ia = len(sugestoes)
        except Exception as exc:  # noqa: BLE001 - IA é opcional, import não pode cair
            log.warning("Fallback de categoria por IA falhou: %s", exc)
            aviso_ia = "Não consegui sugerir categoria por IA; revise as marcadas."

    return jsonify(
        {
            "resumo": {
                "referencia": fatura.resumo.referencia,
                "total": fatura.resumo.total,
                "vencimento": fatura.resumo.vencimento,
                "limite_total": fatura.resumo.limite_total,
                "encargos": fatura.resumo.encargos,
                "total_extraido": fatura.total_extraido,
                "total_juros": fatura.total_juros,
                "quantidade": len(fatura.lancamentos),
                "categorias_por_ia": classificados_por_ia,
                "sem_categoria_impressa": len(incertos),
            },
            "lancamentos": [
                {**l.to_dict(), "categoria_incerta": l.categoria_incerta}
                for l in fatura.lancamentos
            ],
            "parcelas_futuras": [p.__dict__ for p in fatura.parcelas_futuras],
            "linhas_ignoradas": fatura.linhas_ignoradas[:20],
            "aviso_ia": aviso_ia,
        }
    )


@api.post("/fatura/confirmar")
@exige_login
def fatura_confirmar():
    """Salva os lançamentos revisados. Reimportar a mesma fatura não duplica."""
    payload = request.get_json(silent=True) or {}
    lancamentos = payload.get("lancamentos") or []
    if not lancamentos:
        return jsonify({"erro": "Nenhum lançamento para salvar."}), 400

    referencia = (payload.get("referencia") or "").strip()
    # Qual cartão originou esta fatura — liga o import à linha do orçamento.
    cartao = (payload.get("cartao") or "").strip()[:40] or None

    permitidos = {
        "data", "estabelecimento", "valor", "categoria", "origem",
        "fatura_referencia", "tem_juros", "valor_juros", "criado_via",
        "observacoes", "parcela_atual", "parcela_total", "moeda_origem",
        "valor_origem", "cartao", "hash_dedupe",
    }
    limpos = []
    for bruto in lancamentos:
        linha = {k: v for k, v in bruto.items() if k in permitidos}
        if not linha.get("hash_dedupe") or not linha.get("data"):
            continue
        linha["criado_via"] = "import_fatura"
        linha["origem"] = "cartao"
        if referencia:
            linha["fatura_referencia"] = referencia
        if cartao:
            linha["cartao"] = cartao
        limpos.append(linha)

    if not limpos:
        return jsonify({"erro": "Lançamentos inválidos."}), 400

    if cartao:
        # Sem isto, uma compra igual no mesmo dia em dois cartões diferentes
        # seria descartada como duplicata na segunda fatura importada.
        import hashlib

        for linha in limpos:
            linha["hash_dedupe"] = hashlib.sha256(
                f"{cartao}|{linha['hash_dedupe']}".encode()
            ).hexdigest()[:32]

    repo = get_repo()
    resultado = repo.inserir_gastos(limpos)

    resumo = payload.get("resumo") or {}
    if referencia:
        resumo["referencia"] = referencia
    if resumo.get("referencia"):
        repo.salvar_fatura(resumo, payload.get("parcelas_futuras") or [])

    return jsonify(resultado)


@api.get("/faturas")
@exige_login
def listar_faturas():
    return jsonify({"faturas": get_repo().listar_faturas()})
