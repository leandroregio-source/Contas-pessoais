"""Testes do orçamento — conferidos contra a planilha real do usuário."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import orcamento as orc

# Recorte fiel da planilha "Controle Financeiro Pessoal — 2026".
LINHAS = [
    {"id": "r1", "secao": "receita", "nome": "Salário / Renda Principal", "ordem": 0,
     "chave": "salario-renda-principal", "ativo": True},
    {"id": "r2", "secao": "receita", "nome": "Outras Receitas", "ordem": 1,
     "chave": "outras-receitas", "ativo": True},
    {"id": "f1", "secao": "fixa", "nome": "Moradia", "ordem": 0, "chave": "moradia", "ativo": True},
    {"id": "f2", "secao": "fixa", "nome": "Educação / Escola", "ordem": 1,
     "chave": "educacao-escola", "ativo": True},
    {"id": "c1", "secao": "cartao", "nome": "Itaú Latam", "ordem": 0,
     "chave": "itau-latam", "ativo": True},
    {"id": "c2", "secao": "cartao", "nome": "Amex", "ordem": 1, "chave": "amex", "ativo": True},
]


def valores_agosto_em_diante(pares):
    """Aplica os mesmos valores de ago a dez, como na planilha."""
    v = {}
    for mes in ["2026-08", "2026-09", "2026-10", "2026-11", "2026-12"]:
        for lid, val in pares.items():
            v[(lid, mes)] = val
    return v


def test_chave_estavel_e_sem_acento():
    assert orc.chave_de("Itaú Personalité (Esposa)") == "itau-personalite-esposa"
    assert orc.chave_de("Água / Esgoto") == "agua-esgoto"


def test_mes_anterior_atravessa_o_ano():
    assert orc.mes_anterior("2026-01") == "2025-12"
    assert orc.mes_anterior("2026-08") == "2026-07"


def test_soma_das_secoes():
    v = valores_agosto_em_diante({"r1": 32000, "r2": 600, "f1": 1760, "f2": 5850,
                                  "c1": 8600, "c2": 475})
    ago = orc.calcular_ano(LINHAS, v, 2026)[7]
    assert ago.mes == "2026-08"
    assert ago.receitas == 32600.0
    assert ago.fixas == 7610.0
    assert ago.cartoes == 9075.0
    assert ago.saidas == 16685.0
    assert ago.resultado == 32600.0 - 16685.0


def test_saldo_encadeia_de_um_mes_para_o_outro():
    """O Saldo Final de agosto tem que abrir setembro — como na planilha."""
    v = valores_agosto_em_diante({"r1": 32000, "r2": 600, "f1": 1760, "f2": 5850})
    v[("c1", "2026-08")] = 8600      # cartão só em agosto
    meses = orc.calcular_ano(LINHAS, v, 2026, saldo_inicial={"mes": "2026-08", "valor": 0})
    ago, setembro, out = meses[7], meses[8], meses[9]

    assert ago.abertura == 0.0
    assert ago.final == round(32600 - (7610 + 8600), 2)
    assert setembro.abertura == ago.final
    assert setembro.cartoes == 0.0
    assert setembro.final == round(setembro.abertura + setembro.resultado, 2)
    assert out.abertura == setembro.final


def test_saldo_inicial_digitado_substitui_a_corrente():
    v = valores_agosto_em_diante({"r1": 1000})
    meses = orc.calcular_ano(LINHAS, v, 2026,
                             saldo_inicial={"mes": "2026-10", "valor": 5000})
    assert meses[9].abertura == 5000.0, "outubro usa o saldo digitado"
    assert meses[10].abertura == meses[9].final, "novembro volta a encadear"


def test_totais_do_ano():
    v = valores_agosto_em_diante({"r1": 32000, "r2": 600, "f1": 1760, "f2": 5850})
    meses = orc.calcular_ano(LINHAS, v, 2026)
    t = orc.totais_do_ano(meses)
    assert t["receitas"] == 32600 * 5          # ago..dez
    assert t["fixas"] == 7610 * 5
    assert t["saldo_final"] == meses[-1].final


def test_total_por_linha_no_ano():
    v = valores_agosto_em_diante({"r1": 32000})
    assert orc.total_por_linha_no_ano(LINHAS, v, 2026)["r1"] == 160000.0


def test_linha_inativa_sai_da_conta():
    linhas = [dict(l) for l in LINHAS]
    linhas[0]["ativo"] = False
    v = valores_agosto_em_diante({"r1": 32000, "r2": 600})
    ago = orc.calcular_ano(linhas, v, 2026)[7]
    assert ago.receitas == 600.0
    assert all(l.linha_id != "r1" for l in ago.linhas)


# ------------------------------------------------------------- realizado ---

def gasto(valor, *, data, origem="cartao", fatura=None, cartao=None):
    return {"valor": valor, "data": data, "origem": origem,
            "fatura_referencia": fatura, "cartao": cartao}


def test_realizado_de_cartao_usa_o_mes_da_fatura():
    """Compra de 28/08 na fatura de setembro pertence a setembro:
    é em setembro que o dinheiro sai da conta."""
    r = orc.realizado_dos_gastos([
        gasto(100, data="2026-08-28", fatura="2026-09", cartao="itau-latam"),
        gasto(50, data="2026-09-02", fatura="2026-09", cartao="itau-latam"),
    ])
    assert "2026-08" not in r
    assert r["2026-09"]["total"] == 150.0
    assert r["2026-09"]["cartoes"]["itau-latam"] == 150.0


def test_realizado_de_pix_usa_a_data_do_gasto():
    r = orc.realizado_dos_gastos([gasto(80, data="2026-09-10", origem="pix")])
    assert r["2026-09"]["total"] == 80.0
    assert r["2026-09"]["cartoes"] == {}


def test_realizado_separa_cartoes():
    r = orc.realizado_dos_gastos([
        gasto(8600, data="2026-09-01", fatura="2026-09", cartao="itau-latam"),
        gasto(475, data="2026-09-01", fatura="2026-09", cartao="amex"),
    ])
    assert r["2026-09"]["cartoes"] == {"itau-latam": 8600.0, "amex": 475.0}
    assert r["2026-09"]["total"] == 9075.0


def test_previsto_x_realizado_por_linha():
    v = valores_agosto_em_diante({"c1": 8600, "c2": 475})
    real = orc.realizado_dos_gastos([
        gasto(9200, data="2026-09-01", fatura="2026-09", cartao="itau-latam"),
    ])
    setembro = orc.calcular_ano(LINHAS, v, 2026, realizado=real)[8]
    latam = next(l for l in setembro.linhas if l.chave == "itau-latam")
    amex = next(l for l in setembro.linhas if l.chave == "amex")

    assert latam.previsto == 8600.0
    assert latam.realizado == 9200.0
    assert latam.diferenca == 600.0, "estourou o previsto em 600"
    # Cartão sem nenhum lançamento no mês fica DESCONHECIDO, não zero.
    # "Fatura ainda não importada" e "não gastei nada" são coisas diferentes,
    # e mostrar R$ 0 exibiria uma economia de R$ 475 que não aconteceu.
    assert amex.realizado is None
    assert amex.diferenca is None
    assert setembro.realizado_total == 9200.0


def test_linha_sem_medicao_possivel_nao_inventa_realizado():
    """Não há vínculo 1-para-1 entre 'Energia Elétrica' e um gasto do banco.
    Melhor devolver None do que um número que parece medido e não é."""
    v = valores_agosto_em_diante({"f1": 1760})
    setembro = orc.calcular_ano(LINHAS, v, 2026, realizado={"2026-09": {"total": 500}})[8]
    moradia = next(l for l in setembro.linhas if l.chave == "moradia")
    assert moradia.realizado is None
    assert moradia.diferenca is None
