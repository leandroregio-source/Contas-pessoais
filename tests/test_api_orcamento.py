"""Testes das rotas do orçamento."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _init(cliente):
    r = cliente.post("/api/orcamento/inicializar")
    assert r.status_code == 200
    return {l["chave"]: l for l in cliente.get("/api/orcamento?ano=2026").get_json()["linhas"]}


def test_inicializar_cria_as_linhas_da_planilha(cliente):
    linhas = _init(cliente)
    assert len(linhas) == 21
    assert "itau-personalite-esposa" in linhas
    assert linhas["amex"]["secao"] == "cartao"
    assert linhas["salario-renda-principal"]["secao"] == "receita"
    # rodar de novo não duplica
    assert cliente.post("/api/orcamento/inicializar").get_json()["criadas"] == 0


def test_gravar_previsto_e_recalcular(cliente):
    linhas = _init(cliente)
    r = cliente.put("/api/orcamento/valores", json={"valores": [
        {"linha_id": linhas["salario-renda-principal"]["id"], "mes": "2026-08", "previsto": 32000},
        {"linha_id": linhas["outras-receitas"]["id"], "mes": "2026-08", "previsto": "600,00"},
        {"linha_id": linhas["moradia-aluguel-condominio"]["id"], "mes": "2026-08", "previsto": "1.760,00"},
        {"linha_id": linhas["itau-latam"]["id"], "mes": "2026-08", "previsto": 8600},
    ]})
    assert r.get_json()["gravados"] == 4

    ago = cliente.get("/api/orcamento?ano=2026").get_json()["meses"][7]
    assert ago["receitas"] == 32600.0
    assert ago["fixas"] == 1760.0
    assert ago["cartoes"] == 8600.0
    assert ago["saidas"] == 10360.0
    assert ago["resultado"] == 22240.0


def test_saldo_inicial_e_encadeamento(cliente):
    linhas = _init(cliente)
    cliente.put("/api/orcamento/valores", json={"valores": [
        {"linha_id": linhas["salario-renda-principal"]["id"], "mes": "2026-08", "previsto": 1000},
        {"linha_id": linhas["salario-renda-principal"]["id"], "mes": "2026-09", "previsto": 1000},
    ]})
    cliente.put("/api/orcamento/saldo-inicial", json={"mes": "2026-08", "valor": "2.500,00"})

    meses = cliente.get("/api/orcamento?ano=2026").get_json()["meses"]
    assert meses[7]["abertura"] == 2500.0
    assert meses[7]["final"] == 3500.0
    assert meses[8]["abertura"] == 3500.0, "setembro abre com o fechamento de agosto"
    assert meses[8]["final"] == 4500.0


def test_copiar_mes_para_frente(cliente):
    linhas = _init(cliente)
    cliente.put("/api/orcamento/valores", json={"valores": [
        {"linha_id": linhas["internet"]["id"], "mes": "2026-08", "previsto": 150},
        {"linha_id": linhas["iptu"]["id"], "mes": "2026-08", "previsto": 230},
    ]})
    r = cliente.post("/api/orcamento/copiar",
                     json={"de": "2026-08", "para": ["2026-09", "2026-10"]})
    assert r.get_json()["gravados"] == 4

    meses = cliente.get("/api/orcamento?ano=2026").get_json()["meses"]
    assert meses[8]["fixas"] == 380.0
    assert meses[9]["fixas"] == 380.0


def test_copiar_recusa_origem_vazia_ou_igual(cliente):
    _init(cliente)
    assert cliente.post("/api/orcamento/copiar",
                        json={"de": "2026-03", "para": ["2026-04"]}).status_code == 400
    assert cliente.post("/api/orcamento/copiar",
                        json={"de": "2026-03", "para": ["2026-03"]}).status_code == 400


def test_realizado_do_cartao_vem_da_fatura_importada(cliente):
    linhas = _init(cliente)
    cliente.put("/api/orcamento/valores", json={"valores": [
        {"linha_id": linhas["itau-latam"]["id"], "mes": "2026-09", "previsto": 8600},
    ]})
    cliente.post("/api/fatura/confirmar", json={
        "referencia": "2026-09", "cartao": "itau-latam",
        "lancamentos": [
            {"data": "2026-08-20", "estabelecimento": "LATAM", "valor": 5000.0,
             "categoria": "viagem", "hash_dedupe": "h1"},
            {"data": "2026-09-02", "estabelecimento": "HOTEL", "valor": 4200.0,
             "categoria": "viagem", "hash_dedupe": "h2"},
        ],
        "resumo": {"referencia": "2026-09"},
    })

    setembro = cliente.get("/api/orcamento?ano=2026").get_json()["meses"][8]
    latam = next(l for l in setembro["linhas"] if l["chave"] == "itau-latam")
    # a compra de 20/08 entra em setembro: é quando a fatura é paga
    assert latam["realizado"] == 9200.0
    assert latam["diferenca"] == 600.0
    assert setembro["realizado_total"] == 9200.0


def test_usar_realizado_preenche_o_previsto(cliente):
    linhas = _init(cliente)
    cliente.post("/api/fatura/confirmar", json={
        "referencia": "2026-09", "cartao": "amex",
        "lancamentos": [{"data": "2026-09-01", "estabelecimento": "X", "valor": 475.0,
                         "categoria": "outros", "hash_dedupe": "h9"}],
        "resumo": {"referencia": "2026-09"},
    })
    assert cliente.post("/api/orcamento/usar-realizado",
                        json={"mes": "2026-09"}).get_json()["gravados"] == 1

    setembro = cliente.get("/api/orcamento?ano=2026").get_json()["meses"][8]
    amex = next(l for l in setembro["linhas"] if l["chave"] == "amex")
    assert amex["previsto"] == 475.0
    assert amex["diferenca"] == 0.0


def test_faturas_de_cartoes_diferentes_nao_se_anulam(cliente):
    """Mesma compra, mesmo dia, dois cartões: são dois gastos reais."""
    _init(cliente)
    for cartao in ("amex", "itau-azul"):
        cliente.post("/api/fatura/confirmar", json={
            "referencia": "2026-09", "cartao": cartao,
            "lancamentos": [{"data": "2026-09-05", "estabelecimento": "POSTO",
                             "valor": 200.0, "categoria": "servicos",
                             "hash_dedupe": "mesmo-hash"}],
            "resumo": {"referencia": "2026-09"},
        })
    assert cliente.get("/api/gastos").get_json()["quantidade"] == 2


def test_criar_e_remover_linha_propria(cliente):
    _init(cliente)
    r = cliente.post("/api/orcamento/linhas", json={"secao": "fixa", "nome": "Academia"})
    assert r.status_code == 201
    lid = r.get_json()["id"]
    assert r.get_json()["chave"] == "academia"
    # nome repetido é recusado
    assert cliente.post("/api/orcamento/linhas",
                        json={"secao": "fixa", "nome": "Academia"}).status_code == 400
    assert cliente.delete(f"/api/orcamento/linhas/{lid}").status_code == 200
    assert cliente.delete(f"/api/orcamento/linhas/{lid}").status_code == 404


def test_desativar_linha_tira_do_calculo(cliente):
    linhas = _init(cliente)
    lid = linhas["pic"]["id"]
    cliente.put("/api/orcamento/valores",
                json={"valores": [{"linha_id": lid, "mes": "2026-08", "previsto": 535}]})
    assert cliente.get("/api/orcamento?ano=2026").get_json()["meses"][7]["fixas"] == 535.0
    cliente.patch(f"/api/orcamento/linhas/{lid}", json={"ativo": False})
    assert cliente.get("/api/orcamento?ano=2026").get_json()["meses"][7]["fixas"] == 0.0


def test_entradas_invalidas(cliente):
    linhas = _init(cliente)
    lid = linhas["internet"]["id"]
    assert cliente.put("/api/orcamento/valores", json={
        "valores": [{"linha_id": lid, "mes": "2026-13", "previsto": 1}]}).status_code == 400
    assert cliente.put("/api/orcamento/valores", json={
        "valores": [{"linha_id": "inventado", "mes": "2026-01", "previsto": 1}]}).status_code == 400
    assert cliente.put("/api/orcamento/valores", json={
        "valores": [{"linha_id": lid, "mes": "2026-01", "previsto": "abc"}]}).status_code == 400
    assert cliente.post("/api/orcamento/linhas",
                        json={"secao": "cripto", "nome": "X"}).status_code == 400


def test_orcamento_exige_login():
    from app import create_app
    from app.repo import reset_repo
    reset_repo()
    c = create_app({"APP_PIN": "9999", "SQLITE_PATH": "/tmp/orc_pin.sqlite3"}).test_client()
    assert c.get("/api/orcamento").status_code == 401
    assert c.put("/api/orcamento/valores", json={}).status_code == 401
    reset_repo()
