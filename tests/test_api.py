"""Testes das rotas HTTP e da normalização de entrada."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.normalize import DadoInvalido, normalizar_edicao, normalizar_gasto


# ---------------------------------------------------------------- normalize

def test_valor_aceita_formato_brasileiro():
    assert normalizar_gasto({"estabelecimento": "X", "valor": "1.234,56"})["valor"] == 1234.56
    assert normalizar_gasto({"estabelecimento": "X", "valor": "R$ 99,90"})["valor"] == 99.90
    assert normalizar_gasto({"estabelecimento": "X", "valor": 12.5})["valor"] == 12.5


def test_data_aceita_iso_e_br():
    assert normalizar_gasto(
        {"estabelecimento": "X", "valor": 1, "data": "05/03/2026"})["data"] == "2026-03-05"
    assert normalizar_gasto(
        {"estabelecimento": "X", "valor": 1, "data": "2026-03-05"})["data"] == "2026-03-05"


def test_recusa_entrada_invalida():
    with pytest.raises(DadoInvalido):
        normalizar_gasto({"estabelecimento": "", "valor": 10})
    with pytest.raises(DadoInvalido):
        normalizar_gasto({"estabelecimento": "X", "valor": 0})
    with pytest.raises(DadoInvalido):
        normalizar_gasto({"estabelecimento": "X", "valor": "abc"})
    with pytest.raises(DadoInvalido):
        normalizar_gasto({"estabelecimento": "X", "valor": 10, "data": "32/13/2026"})


def test_juros_nao_pode_exceder_o_gasto():
    with pytest.raises(DadoInvalido):
        normalizar_gasto(
            {"estabelecimento": "X", "valor": 100, "tem_juros": True, "valor_juros": 150}
        )


def test_categoria_e_origem_desconhecidas_caem_no_padrao():
    g = normalizar_gasto({"estabelecimento": "X", "valor": 10,
                          "categoria": "cripto", "origem": "bitcoin"})
    assert g["categoria"] == "outros"
    assert g["origem"] == "dinheiro"


def test_edicao_parcial_so_com_campos_enviados():
    assert normalizar_edicao({"valor": "10,00"}) == {"valor": 10.0}
    with pytest.raises(DadoInvalido):
        normalizar_edicao({})


# --------------------------------------------------------------------- API

def test_meta_e_saude(cliente):
    assert cliente.get("/api/saude").get_json() == {"ok": True}
    meta = cliente.get("/api/meta").get_json()
    assert len(meta["categorias"]) == 10
    assert meta["backend"] == "sqlite"


def test_ciclo_completo_do_gasto(cliente):
    criado = cliente.post("/api/gastos", json={
        "estabelecimento": "Padaria do Bairro", "valor": "34,50",
        "data": "2026-09-10", "categoria": "restaurante", "origem": "pix",
    })
    assert criado.status_code == 201
    gid = criado.get_json()["id"]

    lista = cliente.get("/api/gastos").get_json()
    assert lista["quantidade"] == 1 and lista["total"] == 34.50

    editado = cliente.patch(f"/api/gastos/{gid}", json={"categoria": "supermercado"})
    assert editado.get_json()["categoria"] == "supermercado"

    assert cliente.delete(f"/api/gastos/{gid}").status_code == 200
    assert cliente.get("/api/gastos").get_json()["quantidade"] == 0


def test_gasto_invalido_devolve_400(cliente):
    r = cliente.post("/api/gastos", json={"estabelecimento": "", "valor": 10})
    assert r.status_code == 400
    assert "erro" in r.get_json()


def test_editar_inexistente_404(cliente):
    r = cliente.patch("/api/gastos/nao-existe", json={"valor": 10})
    assert r.status_code == 404


def test_filtros_do_historico(cliente):
    for estab, cat, data, origem in [
        ("Mercado A", "supermercado", "2026-08-05", "cartao"),
        ("Bar B", "restaurante", "2026-09-05", "pix"),
        ("Mercado C", "supermercado", "2026-09-20", "cartao"),
    ]:
        cliente.post("/api/gastos", json={"estabelecimento": estab, "valor": 50,
                                          "data": data, "categoria": cat, "origem": origem})
    assert cliente.get("/api/gastos?categoria=supermercado").get_json()["quantidade"] == 2
    assert cliente.get("/api/gastos?origem=pix").get_json()["quantidade"] == 1
    assert cliente.get("/api/gastos?desde=2026-09-01").get_json()["quantidade"] == 2
    assert cliente.get("/api/gastos?busca=Mercado").get_json()["quantidade"] == 2


def test_dashboard_e_insights_com_base_vazia(cliente):
    d = cliente.get("/api/dashboard?mes=2026-09").get_json()
    assert d["total"] == 0 and d["categorias"] == []
    i = cliente.get("/api/insights?mes=2026-09").get_json()
    assert i["sugestoes"] == [] and i["juros"]["total"] == 0


def test_confirmar_fatura_e_idempotente(cliente):
    lanc = [{
        "data": "2026-09-03", "estabelecimento": "SUPERMERCADO X", "valor": 100.0,
        "categoria": "supermercado", "tem_juros": False, "hash_dedupe": "abc123",
    }]
    corpo = {"referencia": "2026-09", "lancamentos": lanc,
             "resumo": {"referencia": "2026-09", "total": 100.0}, "parcelas_futuras": []}
    assert cliente.post("/api/fatura/confirmar", json=corpo).get_json() == {
        "inseridos": 1, "duplicados": 0}
    assert cliente.post("/api/fatura/confirmar", json=corpo).get_json() == {
        "inseridos": 0, "duplicados": 1}
    assert cliente.get("/api/gastos").get_json()["quantidade"] == 1


def test_confirmar_fatura_ignora_campos_nao_previstos(cliente):
    """Payload do cliente não pode injetar coluna arbitrária no banco."""
    cliente.post("/api/fatura/confirmar", json={
        "referencia": "2026-09",
        "lancamentos": [{
            "data": "2026-09-03", "estabelecimento": "X", "valor": 10.0,
            "categoria": "outros", "hash_dedupe": "h1",
            "id": "id-forjado", "criado_em": "1999-01-01", "coluna_inventada": 1,
        }],
    })
    g = cliente.get("/api/gastos").get_json()["gastos"][0]
    assert g["id"] != "id-forjado"
    assert not g["criado_em"].startswith("1999")


def test_pin_protege_a_api():
    from app import create_app
    from app.repo import reset_repo
    reset_repo()
    app = create_app({"APP_PIN": "4321", "SQLITE_PATH": "/tmp/pin_teste.sqlite3"})
    c = app.test_client()
    assert c.get("/api/gastos").status_code == 401
    assert c.get("/").status_code == 302          # redireciona para o login
    assert c.post("/login", data={"pin": "0000"}).status_code == 401
    assert c.post("/login", data={"pin": "4321"}).status_code == 302
    assert c.get("/api/gastos").status_code == 200
    reset_repo()
