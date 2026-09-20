"""API do orçamento mensal — o mesmo modelo da planilha.

Guarda o PREVISTO (digitado, como na planilha) e cruza com o REALIZADO, que
vem dos gastos já lançados. É isso que a planilha não faz: ela sabe o que
você planejou, não o que aconteceu.
"""
from __future__ import annotations

from datetime import date

from flask import Blueprint, jsonify, request

from app.auth import exige_login
from app.repo import get_repo
from app.services import orcamento as orc
from app.services.normalize import DadoInvalido

api_orc = Blueprint("api_orcamento", __name__, url_prefix="/api/orcamento")

CHAVE_SALDO_MES = "saldo_inicial_mes"
CHAVE_SALDO_VALOR = "saldo_inicial_valor"


@api_orc.errorhandler(DadoInvalido)
def _invalido(exc):
    return jsonify({"erro": str(exc)}), 400


def _ano_pedido() -> int:
    try:
        ano = int(request.args.get("ano") or date.today().year)
    except ValueError:
        raise DadoInvalido("Ano inválido.")
    if not 2000 <= ano <= 2100:
        raise DadoInvalido("Ano fora da faixa suportada.")
    return ano


def _valor_numerico(bruto, campo: str) -> float:
    """Aceita '1.234,56' e 1234.56 — o app é digitado no celular."""
    if isinstance(bruto, (int, float)):
        numero = float(bruto)
    else:
        texto = str(bruto or "0").strip().replace("R$", "").replace(" ", "")
        if "," in texto:
            texto = texto.replace(".", "").replace(",", ".")
        try:
            numero = float(texto or 0)
        except ValueError:
            raise DadoInvalido(f"{campo} inválido: {bruto!r}")
    if abs(numero) > 100_000_000:
        raise DadoInvalido(f"{campo} fora da faixa esperada.")
    return round(numero, 2)


def _mes_valido(mes: str) -> str:
    mes = str(mes or "").strip()
    if len(mes) != 7 or mes[4] != "-" or not mes[:4].isdigit() or not mes[5:].isdigit():
        raise DadoInvalido(f"Mês inválido: {mes!r} (esperado AAAA-MM).")
    if not 1 <= int(mes[5:]) <= 12:
        raise DadoInvalido(f"Mês inválido: {mes!r}.")
    return mes


def _saldo_inicial(repo) -> dict:
    mes = repo.obter_config(CHAVE_SALDO_MES)
    if not mes:
        return {}
    try:
        valor = float(repo.obter_config(CHAVE_SALDO_VALOR) or 0)
    except ValueError:
        valor = 0.0
    return {"mes": mes, "valor": valor}


def _realizado_do_ano(repo, ano: int) -> dict:
    """Gastos do ano + dezembro anterior.

    A fatura de janeiro carrega compras de dezembro; sem essa borda, o
    realizado de janeiro sairia incompleto.
    """
    gastos = repo.listar_gastos(desde=f"{ano - 1:04d}-12-01", ate=f"{ano:04d}-12-31")
    return orc.realizado_dos_gastos(gastos)


def _monta_ano(repo, ano: int) -> dict:
    linhas = repo.listar_linhas_orcamento()
    valores = {
        (v["linha_id"], v["mes"]): v["previsto"]
        for v in repo.listar_valores_orcamento(ano)
    }
    meses = orc.calcular_ano(
        linhas, valores, ano,
        saldo_inicial=_saldo_inicial(repo),
        realizado=_realizado_do_ano(repo, ano),
    )
    return {
        "ano": ano,
        "linhas": linhas,
        "meses": [m.to_dict() for m in meses],
        "totais": orc.totais_do_ano(meses),
        "total_por_linha": orc.total_por_linha_no_ano(linhas, valores, ano),
        "saldo_inicial": _saldo_inicial(repo),
        "secoes": [{"chave": s, "rotulo": orc.ROTULO_SECAO[s]} for s in orc.SECOES],
    }


# --------------------------------------------------------------------------

@api_orc.get("")
@exige_login
def ver_ano():
    """Grade anual completa — a planilha inteira."""
    return jsonify(_monta_ano(get_repo(), _ano_pedido()))


@api_orc.post("/inicializar")
@exige_login
def inicializar():
    """Cria as linhas padrão (as mesmas da planilha) se ainda não existirem."""
    repo = get_repo()
    existentes = {l["chave"] for l in repo.listar_linhas_orcamento()}
    criadas = 0
    for ordem, (secao, nome) in enumerate(orc.LINHAS_PADRAO):
        chave = orc.chave_de(nome)
        if chave in existentes:
            continue
        repo.criar_linha_orcamento(
            {"secao": secao, "nome": nome, "chave": chave, "ordem": ordem, "ativo": True}
        )
        criadas += 1
    return jsonify({"criadas": criadas, "ja_existiam": len(existentes)})


@api_orc.post("/linhas")
@exige_login
def criar_linha():
    payload = request.get_json(silent=True) or {}
    nome = str(payload.get("nome") or "").strip()[:80]
    secao = str(payload.get("secao") or "").strip()
    if not nome:
        raise DadoInvalido("Informe o nome da linha.")
    if secao not in orc.SECOES:
        raise DadoInvalido(f"Seção inválida: {secao!r}.")

    repo = get_repo()
    chave = orc.chave_de(nome)
    if any(l["chave"] == chave for l in repo.listar_linhas_orcamento()):
        raise DadoInvalido(f"Já existe uma linha chamada {nome!r}.")

    ordem = payload.get("ordem")
    if ordem is None:
        irmas = [l for l in repo.listar_linhas_orcamento() if l["secao"] == secao]
        ordem = max((l.get("ordem") or 0) for l in irmas) + 1 if irmas else 0

    return jsonify(repo.criar_linha_orcamento(
        {"secao": secao, "nome": nome, "chave": chave, "ordem": int(ordem), "ativo": True}
    )), 201


@api_orc.patch("/linhas/<linha_id>")
@exige_login
def editar_linha(linha_id: str):
    payload = request.get_json(silent=True) or {}
    campos = {}
    if "nome" in payload:
        nome = str(payload["nome"]).strip()[:80]
        if not nome:
            raise DadoInvalido("Informe o nome da linha.")
        campos["nome"] = nome
    if "ativo" in payload:
        campos["ativo"] = bool(payload["ativo"])
    if "ordem" in payload:
        campos["ordem"] = int(payload["ordem"])
    if not campos:
        raise DadoInvalido("Nada para atualizar.")

    atualizada = get_repo().atualizar_linha_orcamento(linha_id, campos)
    if not atualizada:
        return jsonify({"erro": "nao_encontrado"}), 404
    return jsonify(atualizada)


@api_orc.delete("/linhas/<linha_id>")
@exige_login
def remover_linha(linha_id: str):
    if not get_repo().remover_linha_orcamento(linha_id):
        return jsonify({"erro": "nao_encontrado"}), 404
    return jsonify({"ok": True})


@api_orc.put("/valores")
@exige_login
def gravar_valores():
    """Grava um ou vários previstos de uma vez.

    Em lote porque a tela salva a coluna inteira do mês: uma requisição por
    célula deixaria o app lento no celular.
    """
    payload = request.get_json(silent=True) or {}
    brutos = payload.get("valores") or ([payload] if "linha_id" in payload else [])
    if not brutos:
        raise DadoInvalido("Nada para gravar.")

    repo = get_repo()
    validas = {l["id"] for l in repo.listar_linhas_orcamento()}
    itens = []
    for b in brutos:
        linha_id = str(b.get("linha_id") or "")
        if linha_id not in validas:
            raise DadoInvalido(f"Linha desconhecida: {linha_id!r}.")
        itens.append({
            "linha_id": linha_id,
            "mes": _mes_valido(b.get("mes")),
            "previsto": _valor_numerico(b.get("previsto"), "Valor previsto"),
        })
    return jsonify({"gravados": repo.definir_valores_orcamento(itens)})


@api_orc.post("/copiar")
@exige_login
def copiar_mes():
    """Replica os previstos de um mês para outros — o 'arrastar' da planilha."""
    payload = request.get_json(silent=True) or {}
    origem = _mes_valido(payload.get("de"))
    destinos = [_mes_valido(m) for m in (payload.get("para") or [])]
    if not destinos:
        raise DadoInvalido("Informe ao menos um mês de destino.")
    if origem in destinos:
        raise DadoInvalido("O mês de origem não pode ser também o destino.")

    repo = get_repo()
    ano = int(origem[:4])
    do_mes = {
        v["linha_id"]: v["previsto"]
        for v in repo.listar_valores_orcamento(ano) if v["mes"] == origem
    }
    if not do_mes:
        raise DadoInvalido(f"O mês {origem} não tem nenhum valor para copiar.")

    itens = [
        {"linha_id": lid, "mes": destino, "previsto": previsto}
        for destino in destinos
        for lid, previsto in do_mes.items()
    ]
    return jsonify({"gravados": repo.definir_valores_orcamento(itens),
                    "meses": destinos})


@api_orc.put("/saldo-inicial")
@exige_login
def definir_saldo_inicial():
    payload = request.get_json(silent=True) or {}
    mes = _mes_valido(payload.get("mes"))
    valor = _valor_numerico(payload.get("valor"), "Saldo inicial")
    repo = get_repo()
    repo.definir_config(CHAVE_SALDO_MES, mes)
    repo.definir_config(CHAVE_SALDO_VALOR, str(valor))
    return jsonify({"mes": mes, "valor": valor})


@api_orc.post("/usar-realizado")
@exige_login
def usar_realizado():
    """Joga o realizado de um cartão para dentro do previsto daquele mês.

    Depois de importar a fatura, o valor exato já está no banco: digitá-lo de
    novo à mão é retrabalho e fonte de erro de digitação.
    """
    payload = request.get_json(silent=True) or {}
    mes = _mes_valido(payload.get("mes"))
    repo = get_repo()

    realizado = _realizado_do_ano(repo, int(mes[:4])).get(mes, {}).get("cartoes", {})
    if not realizado:
        raise DadoInvalido(
            f"Nenhuma fatura importada com cartão identificado em {mes}."
        )

    linhas = {l["chave"]: l for l in repo.listar_linhas_orcamento()
              if l["secao"] == "cartao"}
    pedidas = payload.get("chaves")
    itens = [
        {"linha_id": linhas[chave]["id"], "mes": mes, "previsto": valor}
        for chave, valor in realizado.items()
        if chave in linhas and (not pedidas or chave in pedidas)
    ]
    if not itens:
        raise DadoInvalido("Nenhuma linha de cartão corresponde às faturas importadas.")
    return jsonify({"gravados": repo.definir_valores_orcamento(itens),
                    "cartoes": [i["linha_id"] for i in itens]})
