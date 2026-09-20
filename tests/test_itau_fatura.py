"""Testes do parser de fatura Itaú — regra pura, sem rede."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.itau_fatura import parse_fatura, parse_valor, _extrai_parcela

FATURA = """
Itaú Uniclass Visa Infinite
Data de vencimento: 05/08/2026
Total desta fatura R$ 4.812,37
Limite total de crédito R$ 25.000,00

Lançamentos: compras e saques
data estabelecimento categoria valor
03/07 SUPERMERCADO ANGELONI supermercado 487,22
04/07 IFOOD*RESTAURANTE SUSHI restaurante 96,40
05/07 DROGARIA SAO PAULO saúde 132,15
08/07 POSTO IPIRANGA 245 serviços 300,00
09/07 CINEMARK SHOPPING lazer 78,00
12/07 RENNER FILIAL 118 vestuário 259,90
14/07 UDEMY CURSOS ONLINE educação 49,90
15/07 DETRAN MG LICENCIAMENTO government 189,44
18/07 LATAM AIRLINES PARC 02/06 viagem 412,30
20/07 PADARIA DO BAIRRO 34,50
22/07 ESTORNO COMPRA DUPLICADA outros -96,40

Lançamentos internacionais
data estabelecimento US$ R$
06/07 OPENAI *CHATGPT SUBSCR 20,00 112,45
11/07 STEAMGAMES.COM 9,99 56,18

Lançamentos: produtos e serviços
10/07 PIX PARCELADO CONTRATO 8832 - Principal 1.200,00
10/07 PIX PARCELADO CONTRATO 8832 - Juros 187,63
25/07 SEGURO PERDA E ROUBO CARTAO 19,90
26/07 JUROS DE CREDITO ROTATIVO 94,12

Compras parceladas - próximas faturas
LATAM AIRLINES 02/06 1.649,20 412,30
NOTEBOOK DELL 04/10 2.400,00 400,00
"""


def parse():
    return parse_fatura(FATURA, referencia="2026-07")


def test_valores():
    assert parse_valor("1.234,56") == 1234.56
    assert parse_valor("R$ 99,00") == 99.0
    assert parse_valor("-96,40") == -96.40


def test_parcelas():
    assert _extrai_parcela("LATAM PARC 02/06") == (2, 6)
    assert _extrai_parcela("NOTEBOOK 04/10") == (4, 10)
    assert _extrai_parcela("PADARIA") == (None, None)
    # 12/10 não é parcela válida (atual > total)
    assert _extrai_parcela("LOJA 12/10") == (None, None)


def test_resumo():
    f = parse()
    assert f.resumo.total == 4812.37
    assert f.resumo.limite_total == 25000.00
    assert f.resumo.vencimento == "2026-08-05"
    assert f.resumo.referencia == "2026-07"


def test_usa_categoria_impressa():
    f = parse()
    por_estab = {l.estabelecimento: l for l in f.lancamentos}
    assert por_estab["SUPERMERCADO ANGELONI"].categoria == "supermercado"
    assert por_estab["DROGARIA SAO PAULO"].categoria == "saude"
    assert por_estab["RENNER FILIAL 118"].categoria == "vestuario"
    assert por_estab["DETRAN MG LICENCIAMENTO"].categoria == "government"
    assert por_estab["UDEMY CURSOS ONLINE"].categoria == "educacao"
    # a categoria não pode sobrar no nome do estabelecimento
    assert "supermercado" not in por_estab["SUPERMERCADO ANGELONI"].estabelecimento.lower()[12:]


def test_linha_sem_categoria_fica_incerta():
    f = parse()
    padaria = next(l for l in f.lancamentos if "PADARIA" in l.estabelecimento)
    assert padaria.categoria_incerta is True
    assert padaria.categoria == "outros"
    assert padaria.valor == 34.50


def test_datas_com_ano_resolvido():
    f = parse()
    assert all(l.data.startswith("2026-07") for l in f.lancamentos if l.data.startswith("2026-07"))
    angeloni = next(l for l in f.lancamentos if "ANGELONI" in l.estabelecimento)
    assert angeloni.data == "2026-07-03"


def test_internacional_usa_valor_em_reais():
    f = parse()
    openai = next(l for l in f.lancamentos if "OPENAI" in l.estabelecimento)
    assert openai.valor == 112.45
    assert openai.valor_origem == 20.00
    assert openai.moeda_origem == "USD"


def test_parcela_detectada():
    f = parse()
    latam = next(l for l in f.lancamentos if "LATAM" in l.estabelecimento)
    assert (latam.parcela_atual, latam.parcela_total) == (2, 6)
    assert latam.categoria == "viagem"


def test_principal_e_juros_viram_um_lancamento():
    f = parse()
    pix = [l for l in f.lancamentos if "PIX PARCELADO" in l.estabelecimento]
    assert len(pix) == 1, f"esperado 1 lançamento fundido, veio {len(pix)}"
    assert pix[0].tem_juros is True
    assert pix[0].valor_juros == 187.63
    assert pix[0].valor == 1387.63  # principal + juros


def test_rotativo_marcado_como_juros():
    f = parse()
    rot = next(l for l in f.lancamentos if "ROTATIVO" in l.estabelecimento)
    assert rot.tem_juros is True
    assert rot.valor_juros == 94.12


def test_estorno_negativo_preservado():
    f = parse()
    est = next(l for l in f.lancamentos if "ESTORNO" in l.estabelecimento)
    assert est.valor == -96.40


def test_ruido_descartado():
    f = parse()
    nomes = " ".join(l.estabelecimento.lower() for l in f.lancamentos)
    assert "total desta fatura" not in nomes
    assert "limite total" not in nomes
    assert "data estabelecimento" not in nomes


def test_parcelas_futuras():
    f = parse()
    assert len(f.parcelas_futuras) == 2
    dell = next(p for p in f.parcelas_futuras if "DELL" in p.descricao)
    assert (dell.parcela_atual, dell.parcela_total) == (4, 10)
    assert dell.valor_parcela == 400.00


def test_hash_estavel_e_unico():
    a, b = parse(), parse()
    ha = [l.hash_dedupe for l in a.lancamentos]
    hb = [l.hash_dedupe for l in b.lancamentos]
    assert ha == hb, "reimportar a mesma fatura deve gerar os mesmos hashes"
    assert len(set(ha)) == len(ha), "hashes devem ser únicos dentro da fatura"


def test_total_juros_agregado():
    f = parse()
    assert f.total_juros == round(187.63 + 94.12, 2)


def test_nome_nao_perde_letra_antes_do_valor():
    """'SUBSCR 20,00': o R final é do nome, não o 'R$' do valor."""
    f = parse_fatura(
        "Lançamentos internacionais\n06/07 OPENAI *CHATGPT SUBSCR 20,00 112,45\n",
        referencia="2026-07",
    )
    assert f.lancamentos[0].estabelecimento == "OPENAI *CHATGPT SUBSCR"
    assert f.lancamentos[0].valor == 112.45


def test_produtos_e_servicos_nao_vai_para_ia():
    f = parse()
    pix = next(l for l in f.lancamentos if "PIX PARCELADO" in l.estabelecimento)
    assert pix.categoria == "servicos"
    assert pix.categoria_incerta is False, "a seção já define a natureza"


def test_descricao_de_parcela_futura_sem_valores():
    f = parse()
    dell = next(p for p in f.parcelas_futuras if "DELL" in p.descricao)
    assert dell.descricao == "NOTEBOOK DELL 04/10"
    assert "2.400" not in dell.descricao
    assert dell.valor_parcela == 400.00
    assert dell.valor_restante == 2400.00
