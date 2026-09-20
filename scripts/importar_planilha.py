#!/usr/bin/env python3
"""Importa a planilha "Controle Financeiro Pessoal" (.xlsx) para o orçamento.

    python scripts/importar_planilha.py Contas_pessoais.xlsx
    python scripts/importar_planilha.py Contas_pessoais.xlsx --simular

Lê a estrutura pelo conteúdo, não por número de linha fixo: acha o cabeçalho
Jan..Dez, segue os marcadores de seção (RECEITAS / DESPESAS FIXAS / CARTÕES)
e ignora as linhas de total, que o app recalcula. Rodar de novo sobrescreve
os previstos do mesmo ano — é idempotente.

Depende de openpyxl:  pip install openpyxl
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.repo import get_repo                       # noqa: E402
from app.services import orcamento as orc           # noqa: E402

MESES_CABECALHO = ("jan", "fev", "mar", "abr", "mai", "jun",
                   "jul", "ago", "set", "out", "nov", "dez")

MARCADORES = {
    "receitas": "receita",
    "despesas fixas": "fixa",
    "cartoes de credito": "cartao",
    "cartões de crédito": "cartao",
}

# Linhas que o app calcula sozinho — importá-las duplicaria tudo.
IGNORAR = ("total", "resumo", "saldo final", "resultado do mes",
           "resultado do mês", "saldo de abertura")


def sem_acento(t: str) -> str:
    nfkd = unicodedata.normalize("NFKD", str(t or ""))
    return "".join(c for c in nfkd if not unicodedata.combining(c)).strip()


def num(v) -> float:
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    if not v:
        return 0.0
    texto = re.sub(r"[^\d,.-]", "", str(v))
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return round(float(texto or 0), 2)
    except ValueError:
        return 0.0


def ler_planilha(caminho: Path) -> dict:
    try:
        import openpyxl
    except ImportError:
        sys.exit("Falta o openpyxl:  pip install openpyxl")

    wb = openpyxl.load_workbook(caminho, data_only=True)
    ws = wb[wb.sheetnames[0]]

    # 1. Ano — do título, com o ano corrente como reserva.
    ano = None
    for linha in ws.iter_rows(min_row=1, max_row=4, values_only=True):
        for v in linha:
            m = re.search(r"\b(20\d{2})\b", str(v or ""))
            if m:
                ano = int(m.group(1))
                break
        if ano:
            break
    if not ano:
        from datetime import date
        ano = date.today().year

    # 2. Cabeçalho: qual coluna é qual mês.
    col_do_mes: dict[int, str] = {}
    linha_cabecalho = None
    for r in range(1, min(ws.max_row, 15) + 1):
        achados = {}
        for c in range(1, ws.max_column + 1):
            rotulo = sem_acento(ws.cell(r, c).value).lower()[:3]
            if rotulo in MESES_CABECALHO:
                achados[c] = f"{ano:04d}-{MESES_CABECALHO.index(rotulo) + 1:02d}"
        if len(achados) >= 6:
            col_do_mes, linha_cabecalho = achados, r
            break
    if not col_do_mes:
        sys.exit("Não achei o cabeçalho com os meses (Jan..Dez) na planilha.")

    # A coluna dos rótulos é a primeira à esquerda com texto no cabeçalho.
    col_rotulo = min(col_do_mes) - 1

    # 3. Linhas, por seção.
    secao = None
    linhas: list[dict] = []
    aberturas: dict[str, float] = {}

    for r in range(linha_cabecalho + 1, ws.max_row + 1):
        rotulo = str(ws.cell(r, col_rotulo).value or "").strip()
        if not rotulo:
            continue
        chave_rotulo = sem_acento(rotulo).lower()

        if chave_rotulo in MARCADORES:
            secao = MARCADORES[chave_rotulo]
            continue
        if chave_rotulo in ("saldo", "resumo"):
            secao = None
            continue

        if chave_rotulo.startswith("saldo de abertura"):
            for c, mes in col_do_mes.items():
                aberturas[mes] = num(ws.cell(r, c).value)
            continue
        if any(chave_rotulo.startswith(x) for x in IGNORAR):
            continue
        if secao is None:
            continue

        valores = {mes: num(ws.cell(r, c).value) for c, mes in col_do_mes.items()}
        linhas.append({"secao": secao, "nome": rotulo,
                       "chave": orc.chave_de(rotulo), "valores": valores})

    # 4. Saldo inicial = a abertura do primeiro mês que tem qualquer movimento.
    #    Antes disso a planilha é só zero, e importar isso não diz nada.
    meses_com_dado = sorted({
        mes for l in linhas for mes, v in l["valores"].items() if v
    })
    saldo_inicial = None
    if meses_com_dado:
        primeiro = meses_com_dado[0]
        saldo_inicial = {"mes": primeiro, "valor": aberturas.get(primeiro, 0.0)}

    return {"ano": ano, "linhas": linhas, "saldo_inicial": saldo_inicial,
            "meses_com_dado": meses_com_dado}


def main() -> None:
    ap = argparse.ArgumentParser(description="Importa a planilha para o orçamento do app.")
    ap.add_argument("planilha", type=Path)
    ap.add_argument("--simular", action="store_true",
                    help="mostra o que faria, sem gravar nada")
    args = ap.parse_args()

    if not args.planilha.exists():
        sys.exit(f"Arquivo não encontrado: {args.planilha}")

    dados = ler_planilha(args.planilha)
    print(f"Planilha: {args.planilha.name}  ·  ano {dados['ano']}")
    print(f"Meses com movimento: {', '.join(dados['meses_com_dado']) or '(nenhum)'}")
    if dados["saldo_inicial"]:
        si = dados["saldo_inicial"]
        print(f"Saldo inicial: {si['mes']} = R$ {si['valor']:,.2f}")

    por_secao: dict[str, list] = {}
    for l in dados["linhas"]:
        por_secao.setdefault(l["secao"], []).append(l)
    for secao in orc.SECOES:
        itens = por_secao.get(secao, [])
        print(f"\n{orc.ROTULO_SECAO[secao]} ({len(itens)} linhas)")
        for l in itens:
            total = sum(l["valores"].values())
            print(f"   {l['nome'][:42]:<42} total do ano R$ {total:>12,.2f}")

    if args.simular:
        print("\n(--simular: nada foi gravado)")
        return

    repo = get_repo()
    existentes = {l["chave"]: l for l in repo.listar_linhas_orcamento()}
    itens, criadas = [], 0

    for ordem, l in enumerate(dados["linhas"]):
        atual = existentes.get(l["chave"])
        if atual is None:
            atual = repo.criar_linha_orcamento({
                "secao": l["secao"], "nome": l["nome"], "chave": l["chave"],
                "ordem": ordem, "ativo": True,
            })
            existentes[l["chave"]] = atual
            criadas += 1
        itens += [
            {"linha_id": atual["id"], "mes": mes, "previsto": valor}
            for mes, valor in l["valores"].items()
        ]

    gravados = repo.definir_valores_orcamento(itens)
    if dados["saldo_inicial"]:
        repo.definir_config("saldo_inicial_mes", dados["saldo_inicial"]["mes"])
        repo.definir_config("saldo_inicial_valor", str(dados["saldo_inicial"]["valor"]))

    print(f"\nPronto: {criadas} linhas criadas, {gravados} valores gravados.")


if __name__ == "__main__":
    main()
