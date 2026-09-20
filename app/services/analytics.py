"""Análise dos gastos: agregações, tendências, recorrências e sugestões.

Regra pura — recebe listas de dicts (as linhas do banco) e devolve dicts.
Nada aqui toca rede ou banco, o que mantém tudo testável e barato: a análise
roda em memória sobre a janela de meses pedida, não no cliente.
"""
from __future__ import annotations

import re
import statistics
from collections import defaultdict
from datetime import date

from app.categorias import CATEGORIAS, rotulo, sem_acento

# Ruído em nome de estabelecimento de cartão: forma societária, sufixo de
# loja/filial, TLD, número de terminal. Removido só para agrupar recorrências —
# o nome original continua intacto no banco.
_TOKENS_RUIDO = {
    "ltda", "me", "epp", "sa", "s", "filial", "fil", "loja", "cnpj", "www",
    "com", "br", "net", "app", "online", "pag", "pagto", "pagamento", "cartao",
    "rj", "sp", "mg", "pr", "sc", "rs", "ba", "pe", "ce", "go", "df", "es",
}

# Primeira palavra genérica demais para identificar o estabelecimento sozinha:
# "supermercado" casaria todo supermercado do extrato num grupo só.
_TOKENS_GENERICOS = {
    "supermercado", "mercado", "restaurante", "bar", "padaria", "posto",
    "farmacia", "drogaria", "academia", "clinica", "hospital", "escola",
    "colegio", "curso", "hotel", "pousada", "estacionamento", "auto", "casa",
    "centro", "shopping", "super", "mini", "distribuidora", "comercio",
}


# --------------------------------------------------------------------------
# Helpers de período
# --------------------------------------------------------------------------

def mes_de(iso: str) -> str:
    return (iso or "")[:7]


def mes_anterior(mes: str) -> str:
    ano, m = int(mes[:4]), int(mes[5:7])
    return f"{ano - 1:04d}-12" if m == 1 else f"{ano:04d}-{m - 1:02d}"


def ultimos_meses(mes: str, n: int) -> list[str]:
    saida, atual = [], mes
    for _ in range(n):
        saida.append(atual)
        atual = mes_anterior(atual)
    return list(reversed(saida))


def mes_atual() -> str:
    return date.today().strftime("%Y-%m")


def _v(g: dict, campo: str, default=0.0):
    valor = g.get(campo)
    return default if valor is None else valor


def _valor(g: dict) -> float:
    return float(_v(g, "valor"))


def chave_estabelecimento(nome: str) -> str:
    """Chave de agrupamento por estabelecimento.

    Precisa casar 'NETFLIX.COM' com 'NETFLIX *ASSINATURA 22' — a operadora
    muda o sufixo do descritor de um mês pro outro e a assinatura sumiria da
    detecção de recorrência. A marca fica na PRIMEIRA palavra, então é ela que
    vira a chave; só quando essa palavra é genérica demais ('supermercado',
    'posto') a segunda entra junto, senão todo mercado viraria um grupo só.
    """
    base = sem_acento(nome or "").lower()
    base = re.sub(r"[^a-z0-9]+", " ", base)
    tokens = [
        t for t in base.split()
        if t and t not in _TOKENS_RUIDO and not t.isdigit() and len(t) > 1
    ]
    if not tokens:
        return ""
    if tokens[0] in _TOKENS_GENERICOS and len(tokens) > 1:
        return f"{tokens[0]} {tokens[1]}"[:40]
    return tokens[0][:40]


# --------------------------------------------------------------------------
# Agregações
# --------------------------------------------------------------------------

def total_por_categoria(gastos: list[dict]) -> dict[str, float]:
    acc: dict[str, float] = defaultdict(float)
    for g in gastos:
        acc[g.get("categoria") or "outros"] += _valor(g)
    return {k: round(v, 2) for k, v in acc.items()}


def total_por_mes(gastos: list[dict]) -> dict[str, float]:
    acc: dict[str, float] = defaultdict(float)
    for g in gastos:
        acc[mes_de(g.get("data", ""))] += _valor(g)
    return {k: round(v, 2) for k, v in acc.items()}


def total_por_origem(gastos: list[dict]) -> dict[str, float]:
    acc: dict[str, float] = defaultdict(float)
    for g in gastos:
        acc[g.get("origem") or "cartao"] += _valor(g)
    return {k: round(v, 2) for k, v in acc.items()}


def _pct(atual: float, anterior: float) -> float | None:
    """Variação percentual. None quando não há base de comparação."""
    if anterior == 0:
        return None
    return round((atual - anterior) / abs(anterior) * 100, 1)


def comparativo_categorias(gastos: list[dict], mes: str) -> list[dict]:
    """Categoria a categoria: mês atual x mês anterior, ordenado por gasto."""
    do_mes = [g for g in gastos if mes_de(g.get("data", "")) == mes]
    do_anterior = [g for g in gastos if mes_de(g.get("data", "")) == mes_anterior(mes)]
    atual = total_por_categoria(do_mes)
    anterior = total_por_categoria(do_anterior)

    linhas = []
    for cat in set(atual) | set(anterior):
        a, b = atual.get(cat, 0.0), anterior.get(cat, 0.0)
        linhas.append(
            {
                "categoria": cat,
                "rotulo": rotulo(cat),
                "atual": round(a, 2),
                "anterior": round(b, 2),
                "delta": round(a - b, 2),
                "delta_pct": _pct(a, b),
            }
        )
    return sorted(linhas, key=lambda x: x["atual"], reverse=True)


def ranking_crescimento(gastos: list[dict], mes: str, minimo: float = 30.0) -> list[dict]:
    """Categorias que mais cresceram em R$ — ignora ruído abaixo de `minimo`."""
    linhas = [l for l in comparativo_categorias(gastos, mes) if l["delta"] >= minimo]
    return sorted(linhas, key=lambda x: x["delta"], reverse=True)


def juros_do_periodo(gastos: list[dict]) -> dict:
    """Quanto saiu em juros — o dinheiro que dava pra não gastar."""
    comjuros = [g for g in gastos if g.get("tem_juros")]
    total = round(sum(float(_v(g, "valor_juros")) for g in comjuros), 2)
    por_mes: dict[str, float] = defaultdict(float)
    for g in comjuros:
        por_mes[mes_de(g.get("data", ""))] += float(_v(g, "valor_juros"))
    return {
        "total": total,
        "quantidade": len(comjuros),
        "por_mes": {k: round(v, 2) for k, v in sorted(por_mes.items())},
        "lancamentos": sorted(
            comjuros, key=lambda g: float(_v(g, "valor_juros")), reverse=True
        )[:20],
    }


# --------------------------------------------------------------------------
# Recorrências
# --------------------------------------------------------------------------

def detectar_recorrentes(
    gastos: list[dict],
    minimo_meses: int = 3,
    tolerancia: float = 0.20,
    referencia: str | None = None,
) -> list[dict]:
    """Assinaturas e cobranças que se repetem todo mês em valor parecido.

    Critério: mesmo estabelecimento normalizado, em >= `minimo_meses` meses
    distintos, com dispersão de valor dentro de `tolerancia` da mediana.
    É assim que uma assinatura esquecida aparece.

    `referencia` é o mês a partir do qual "ainda ativa" é julgado. O default é
    o mês corrente, mas ao analisar um mês passado quem manda é aquele mês —
    senão toda recorrência de um mês antigo parece encerrada.
    """
    grupos: dict[str, list[dict]] = defaultdict(list)
    for g in gastos:
        if _valor(g) <= 0:
            continue
        grupos[chave_estabelecimento(g.get("estabelecimento", ""))].append(g)

    ref = referencia or mes_atual()
    encontrados = []

    for chave, itens in grupos.items():
        if not chave or len(itens) < minimo_meses:
            continue
        meses = sorted({mes_de(g.get("data", "")) for g in itens})
        if len(meses) < minimo_meses:
            continue

        # Parcelamento tem fim; assinatura não. Projetar 12x uma compra
        # parcelada em 3x inventa uma despesa anual que não existe.
        parcelado = [g for g in itens if g.get("parcela_total")]
        if parcelado and len(parcelado) == len(itens):
            continue

        valores = [_valor(g) for g in itens]
        mediana = statistics.median(valores)
        if mediana <= 0:
            continue
        dispersao = max(abs(v - mediana) for v in valores) / mediana
        if dispersao > tolerancia:
            continue

        # Meses consecutivos? Uma lacuna grande sugere compra eventual.
        esperados = ultimos_meses(meses[-1], len(meses))
        consecutivos = meses == esperados

        encontrados.append(
            {
                "chave": chave,
                "estabelecimento": max(
                    (g.get("estabelecimento", "") for g in itens), key=len
                ),
                "categoria": itens[-1].get("categoria", "outros"),
                "meses": meses,
                "qtd_meses": len(meses),
                "valor_medio": round(statistics.mean(valores), 2),
                "valor_mediano": round(mediana, 2),
                "custo_anual_estimado": round(mediana * 12, 2),
                "consecutivos": consecutivos,
                "ultimo_mes": meses[-1],
                "ativa_no_mes_corrente": meses[-1] >= mes_anterior(ref),
            }
        )

    return sorted(encontrados, key=lambda r: r["custo_anual_estimado"], reverse=True)


# --------------------------------------------------------------------------
# Dashboard e insights
# --------------------------------------------------------------------------

def resumo_mensal(gastos: list[dict], mes: str, meses_serie: int = 6) -> dict:
    do_mes = [g for g in gastos if mes_de(g.get("data", "")) == mes]
    ant = mes_anterior(mes)
    do_ant = [g for g in gastos if mes_de(g.get("data", "")) == ant]

    total_mes = round(sum(_valor(g) for g in do_mes), 2)
    total_ant = round(sum(_valor(g) for g in do_ant), 2)

    serie_meses = ultimos_meses(mes, meses_serie)
    por_mes = total_por_mes(gastos)

    por_cat = total_por_categoria(do_mes)
    categorias = sorted(
        (
            {
                "categoria": c,
                "rotulo": rotulo(c),
                "total": v,
                "pct": round(v / total_mes * 100, 1) if total_mes else 0.0,
            }
            for c, v in por_cat.items()
        ),
        key=lambda x: x["total"],
        reverse=True,
    )

    return {
        "mes": mes,
        "mes_anterior": ant,
        "total": total_mes,
        "total_anterior": total_ant,
        "delta": round(total_mes - total_ant, 2),
        "delta_pct": _pct(total_mes, total_ant),
        "quantidade": len(do_mes),
        "ticket_medio": round(total_mes / len(do_mes), 2) if do_mes else 0.0,
        "categorias": categorias,
        "por_origem": total_por_origem(do_mes),
        "serie": [{"mes": m, "total": por_mes.get(m, 0.0)} for m in serie_meses],
        "juros": juros_do_periodo(do_mes)["total"],
        "maiores": sorted(do_mes, key=_valor, reverse=True)[:5],
    }


def gerar_sugestoes(gastos: list[dict], mes: str) -> list[dict]:
    """Sugestões de economia a partir de padrões reais, não de palpite.

    Cada sugestão carrega o valor em R$ que está em jogo, porque uma dica sem
    número não muda comportamento nenhum.
    """
    sugestoes: list[dict] = []
    do_mes = [g for g in gastos if mes_de(g.get("data", "")) == mes]
    historico = ultimos_meses(mes, 7)[:-1]  # 6 meses anteriores, sem o atual
    por_mes = total_por_mes(gastos)

    # 1. Juros — o gasto mais evitável que existe.
    juros = juros_do_periodo(do_mes)
    if juros["total"] > 0:
        sugestoes.append(
            {
                "tipo": "juros",
                "severidade": "alta",
                "titulo": f"R$ {juros['total']:.2f} em juros neste mês",
                "detalhe": (
                    f"{juros['quantidade']} lançamento(s) com juros embutidos. "
                    f"Quitar ou antecipar esses parcelamentos economiza "
                    f"R$ {juros['total'] * 12:.2f}/ano no ritmo atual."
                ),
                "valor": juros["total"],
            }
        )

    # 2. Categorias acima da média histórica.
    for linha in comparativo_categorias(gastos, mes):
        cat = linha["categoria"]
        hist = [
            total_por_categoria(
                [g for g in gastos if mes_de(g.get("data", "")) == m]
            ).get(cat, 0.0)
            for m in historico
        ]
        hist = [h for h in hist if h > 0]
        if len(hist) < 2:
            continue
        media = statistics.mean(hist)
        if media <= 0 or linha["atual"] <= media * 1.25 or linha["atual"] - media < 50:
            continue
        excedente = round(linha["atual"] - media, 2)
        sugestoes.append(
            {
                "tipo": "acima_da_media",
                "severidade": "media",
                "titulo": f"{linha['rotulo']} está {round((linha['atual'] / media - 1) * 100)}% acima da média",
                "detalhe": (
                    f"R$ {linha['atual']:.2f} neste mês contra média de "
                    f"R$ {media:.2f} nos últimos {len(hist)} meses. "
                    f"Excedente: R$ {excedente:.2f}."
                ),
                "valor": excedente,
                "categoria": cat,
            }
        )

    # 3. Recorrências — assinaturas que continuam correndo.
    for rec in detectar_recorrentes(gastos, referencia=mes):
        if not rec["ativa_no_mes_corrente"] or rec["qtd_meses"] < 3:
            continue
        sugestoes.append(
            {
                "tipo": "recorrente",
                "severidade": "baixa" if rec["valor_mediano"] < 50 else "media",
                "titulo": f"{rec['estabelecimento']} se repete há {rec['qtd_meses']} meses",
                "detalhe": (
                    f"R$ {rec['valor_mediano']:.2f}/mês — "
                    f"R$ {rec['custo_anual_estimado']:.2f} por ano. "
                    "Confira se ainda usa."
                ),
                "valor": rec["custo_anual_estimado"],
                "categoria": rec["categoria"],
            }
        )

    # 4. Tendência geral de alta sustentada.
    serie = [por_mes.get(m, 0.0) for m in ultimos_meses(mes, 4)]
    if len(serie) == 4 and all(serie) and serie[3] > serie[0] * 1.15:
        sugestoes.append(
            {
                "tipo": "tendencia",
                "severidade": "media",
                "titulo": "Gasto total em alta há 3 meses",
                "detalhe": (
                    f"De R$ {serie[0]:.2f} para R$ {serie[3]:.2f} "
                    f"({round((serie[3] / serie[0] - 1) * 100)}%)."
                ),
                "valor": round(serie[3] - serie[0], 2),
            }
        )

    ordem = {"alta": 0, "media": 1, "baixa": 2}
    return sorted(sugestoes, key=lambda s: (ordem[s["severidade"]], -s["valor"]))
