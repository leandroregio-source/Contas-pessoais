"""Testes das regras de análise."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import analytics as an


def g(data, estab, valor, categoria="outros", **extra):
    base = {
        "data": data, "estabelecimento": estab, "valor": valor,
        "categoria": categoria, "origem": "cartao", "tem_juros": False,
        "valor_juros": None,
    }
    base.update(extra)
    return base


BASE = [
    # jan
    g("2026-01-05", "SUPERMERCADO BH", 800.0, "supermercado"),
    g("2026-01-10", "NETFLIX.COM", 55.90, "lazer"),
    g("2026-01-12", "ACADEMIA SMART FIT", 129.90, "saude"),
    # fev
    g("2026-02-05", "SUPERMERCADO BH", 820.0, "supermercado"),
    g("2026-02-10", "NETFLIX.COM", 55.90, "lazer"),
    g("2026-02-12", "ACADEMIA SMART FIT", 129.90, "saude"),
    # mar
    g("2026-03-05", "SUPERMERCADO BH", 790.0, "supermercado"),
    g("2026-03-10", "NETFLIX.COM", 55.90, "lazer"),
    g("2026-03-12", "ACADEMIA SMART FIT", 129.90, "saude"),
    # abr — supermercado dispara e entra juros
    g("2026-04-05", "SUPERMERCADO BH", 1500.0, "supermercado"),
    g("2026-04-10", "NETFLIX *ASSINATURA 22", 55.90, "lazer"),
    g("2026-04-12", "ACADEMIA SMART FIT", 129.90, "saude"),
    g("2026-04-20", "PIX PARCELADO 8832", 1200.0, "servicos",
      tem_juros=True, valor_juros=187.63),
]


def test_mes_anterior_vira_o_ano():
    assert an.mes_anterior("2026-01") == "2025-12"
    assert an.mes_anterior("2026-05") == "2026-04"


def test_ultimos_meses_em_ordem():
    assert an.ultimos_meses("2026-03", 4) == ["2025-12", "2026-01", "2026-02", "2026-03"]


def test_total_por_categoria():
    abr = [x for x in BASE if x["data"].startswith("2026-04")]
    assert an.total_por_categoria(abr)["supermercado"] == 1500.0


def test_resumo_mensal():
    r = an.resumo_mensal(BASE, "2026-04")
    assert r["total"] == round(1500 + 55.90 + 129.90 + 1200, 2)
    assert r["total_anterior"] == round(790 + 55.90 + 129.90, 2)
    assert r["delta"] > 0
    assert r["categorias"][0]["categoria"] == "supermercado"
    assert r["juros"] == 187.63
    assert len(r["serie"]) == 6
    assert r["serie"][-1]["mes"] == "2026-04"


def test_delta_pct_sem_base_e_none():
    r = an.resumo_mensal(BASE, "2026-01")
    assert r["delta_pct"] is None  # dez/2025 não existe


def test_ranking_crescimento():
    rk = an.ranking_crescimento(BASE, "2026-04")
    por_cat = {l["categoria"]: l["delta"] for l in rk}
    # serviços sai de 0 para 1200 (o PIX parcelado), então lidera o ranking
    assert rk[0]["categoria"] == "servicos"
    assert por_cat["servicos"] == 1200.0
    assert por_cat["supermercado"] == 710.0
    assert rk == sorted(rk, key=lambda x: x["delta"], reverse=True)


def test_juros_do_periodo():
    j = an.juros_do_periodo(BASE)
    assert j["total"] == 187.63
    assert j["quantidade"] == 1
    assert j["por_mes"]["2026-04"] == 187.63


def test_chave_estabelecimento_agrupa_variacoes():
    assert an.chave_estabelecimento("NETFLIX.COM") == an.chave_estabelecimento(
        "NETFLIX *ASSINATURA 22"
    )
    assert an.chave_estabelecimento("IFOOD*BURGER 123") == an.chave_estabelecimento(
        "IFOOD *BURGER"
    )
    # primeira palavra genérica não pode fundir mercados diferentes
    assert an.chave_estabelecimento("SUPERMERCADO BH") != an.chave_estabelecimento(
        "SUPERMERCADO EPA"
    )


def test_recorrentes_encontra_assinaturas():
    recs = {r["chave"]: r for r in an.detectar_recorrentes(BASE)}
    assert "netflix" in recs
    assert recs["netflix"]["qtd_meses"] == 4
    assert recs["netflix"]["valor_mediano"] == 55.90
    assert recs["netflix"]["custo_anual_estimado"] == round(55.90 * 12, 2)
    assert recs["netflix"]["consecutivos"] is True
    # supermercado varia demais em abril => não é recorrência de valor fixo
    assert not any("supermercado" in k for k in recs)


def test_recorrentes_exige_minimo_de_meses():
    poucos = [g("2026-01-01", "LOJA X", 10.0), g("2026-02-01", "LOJA X", 10.0)]
    assert an.detectar_recorrentes(poucos) == []


def test_sugestoes_priorizam_juros():
    s = an.gerar_sugestoes(BASE, "2026-04")
    assert s, "deveria gerar sugestões"
    assert s[0]["tipo"] == "juros"
    assert s[0]["severidade"] == "alta"
    tipos = {x["tipo"] for x in s}
    assert "acima_da_media" in tipos, "supermercado 1500 vs média ~803 deve acusar"
    assert "recorrente" in tipos


def test_sugestoes_vazias_sem_dados():
    assert an.gerar_sugestoes([], "2026-04") == []


def test_recorrente_ativa_depende_do_mes_analisado():
    """Analisar abril não pode dar a recorrência por encerrada só porque
    o relógio do servidor já está em outro mês."""
    em_abril = {r["chave"]: r for r in an.detectar_recorrentes(BASE, referencia="2026-04")}
    assert em_abril["netflix"]["ativa_no_mes_corrente"] is True
    muito_depois = {
        r["chave"]: r for r in an.detectar_recorrentes(BASE, referencia="2027-01")
    }
    assert muito_depois["netflix"]["ativa_no_mes_corrente"] is False


def test_parcelamento_nao_vira_assinatura():
    """Compra em 3x não é recorrência: projetar 12 meses inventaria despesa."""
    parcelas = [
        g("2026-01-10", "NOTEBOOK DELL", 400.0, "outros", parcela_atual=1, parcela_total=10),
        g("2026-02-10", "NOTEBOOK DELL", 400.0, "outros", parcela_atual=2, parcela_total=10),
        g("2026-03-10", "NOTEBOOK DELL", 400.0, "outros", parcela_atual=3, parcela_total=10),
    ]
    assert an.detectar_recorrentes(parcelas) == []
    # a mesma série SEM marcação de parcela continua sendo recorrência
    sem_marca = [{k: v for k, v in x.items() if not k.startswith("parcela")} for x in parcelas]
    assert len(an.detectar_recorrentes(sem_marca)) == 1
