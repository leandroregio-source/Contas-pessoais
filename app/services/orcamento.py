"""Orçamento mensal — o mesmo modelo da planilha, como regra pura.

Estrutura (igual à planilha "Controle Financeiro Pessoal"):

    Saldo de Abertura        ← Saldo Final do mês anterior
    (+) Receitas             salário, outras
    (−) Despesas Fixas       moradia, energia, escola, seguros…
    (−) Cartões de Crédito   uma linha por cartão
    ─────────────────────────────────────────────
    Total de Saídas   = fixas + cartões
    Resultado do Mês  = receitas − saídas
    Saldo Final       = abertura + resultado   → abre o mês seguinte

O que o app acrescenta sobre a planilha: cada linha tem PREVISTO e REALIZADO.
O previsto é digitado (como na planilha); o realizado vem dos gastos que já
estão no banco — nas linhas de cartão, direto da fatura importada. É a
diferença entre planejar e saber o que de fato aconteceu.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

SECOES = ("receita", "fixa", "cartao")

ROTULO_SECAO = {
    "receita": "Receitas",
    "fixa": "Despesas Fixas",
    "cartao": "Cartões de Crédito",
}


def meses_do_ano(ano: int) -> list[str]:
    return [f"{ano:04d}-{m:02d}" for m in range(1, 13)]


def mes_anterior(mes: str) -> str:
    ano, m = int(mes[:4]), int(mes[5:7])
    return f"{ano - 1:04d}-12" if m == 1 else f"{ano:04d}-{m - 1:02d}"


def chave_de(nome: str) -> str:
    """Slug estável para uma linha — é por ele que um gasto aponta o cartão."""
    base = unicodedata.normalize("NFKD", nome or "")
    base = "".join(c for c in base if not unicodedata.combining(c)).lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", base)).strip("-")[:40]


@dataclass
class LinhaMes:
    linha_id: str
    nome: str
    secao: str
    chave: str
    previsto: float = 0.0
    realizado: float | None = None   # None = não há como medir esta linha

    @property
    def diferenca(self) -> float | None:
        if self.realizado is None:
            return None
        return round(self.realizado - self.previsto, 2)


@dataclass
class ResumoMes:
    mes: str
    abertura: float = 0.0
    receitas: float = 0.0
    fixas: float = 0.0
    cartoes: float = 0.0
    saidas: float = 0.0
    resultado: float = 0.0
    final: float = 0.0
    realizado_total: float | None = None
    linhas: list[LinhaMes] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mes": self.mes,
            "abertura": self.abertura,
            "receitas": self.receitas,
            "fixas": self.fixas,
            "cartoes": self.cartoes,
            "saidas": self.saidas,
            "resultado": self.resultado,
            "final": self.final,
            "realizado_total": self.realizado_total,
            "linhas": [
                {
                    "linha_id": l.linha_id,
                    "nome": l.nome,
                    "secao": l.secao,
                    "chave": l.chave,
                    "previsto": l.previsto,
                    "realizado": l.realizado,
                    "diferenca": l.diferenca,
                }
                for l in self.linhas
            ],
        }


def _num(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def calcular_ano(
    linhas: list[dict],
    valores: dict[tuple[str, str], float],
    ano: int,
    saldo_inicial: dict | None = None,
    realizado: dict[str, dict] | None = None,
) -> list[ResumoMes]:
    """Calcula os 12 meses do ano, encadeando o saldo.

    `valores` mapeia (linha_id, mes) -> previsto.
    `realizado` mapeia mes -> {"total": float, "cartoes": {chave: float}}.
    `saldo_inicial` é {"mes": "AAAA-MM", "valor": float}: o único saldo digitado;
    daí em diante cada abertura é o fechamento do mês anterior.
    """
    realizado = realizado or {}
    saldo_inicial = saldo_inicial or {}
    ativos = [l for l in linhas if l.get("ativo", True)]
    ativos.sort(key=lambda l: (SECOES.index(l.get("secao", "fixa")), l.get("ordem", 0)))

    saldos_finais: dict[str, float] = {}
    meses: list[ResumoMes] = []

    for mes in meses_do_ano(ano):
        rm = ResumoMes(mes=mes)
        real_mes = realizado.get(mes, {})
        real_cartoes = real_mes.get("cartoes", {})

        for l in ativos:
            previsto = _num(valores.get((l["id"], mes), 0))
            # Só a linha de cartão tem realizado com correspondência exata:
            # a fatura importada é daquele cartão e daquele mês. Nas demais
            # não existe vínculo 1-para-1, então não inventamos um número.
            real = real_cartoes.get(l.get("chave")) if l["secao"] == "cartao" else None
            rm.linhas.append(
                LinhaMes(
                    linha_id=l["id"], nome=l["nome"], secao=l["secao"],
                    chave=l.get("chave", ""), previsto=previsto,
                    realizado=None if real is None else _num(real),
                )
            )

        soma = lambda s: round(sum(x.previsto for x in rm.linhas if x.secao == s), 2)
        rm.receitas, rm.fixas, rm.cartoes = soma("receita"), soma("fixa"), soma("cartao")
        rm.saidas = round(rm.fixas + rm.cartoes, 2)
        rm.resultado = round(rm.receitas - rm.saidas, 2)

        if saldo_inicial.get("mes") == mes:
            rm.abertura = _num(saldo_inicial.get("valor"))
        else:
            rm.abertura = saldos_finais.get(mes_anterior(mes), 0.0)

        rm.final = round(rm.abertura + rm.resultado, 2)
        saldos_finais[mes] = rm.final

        if mes in realizado:
            rm.realizado_total = _num(real_mes.get("total"))

        meses.append(rm)

    return meses


def totais_do_ano(meses: list[ResumoMes]) -> dict:
    """Coluna 'Total 2026' da planilha, mais o fechamento do ano."""
    return {
        "receitas": round(sum(m.receitas for m in meses), 2),
        "fixas": round(sum(m.fixas for m in meses), 2),
        "cartoes": round(sum(m.cartoes for m in meses), 2),
        "saidas": round(sum(m.saidas for m in meses), 2),
        "resultado": round(sum(m.resultado for m in meses), 2),
        "saldo_final": meses[-1].final if meses else 0.0,
    }


def total_por_linha_no_ano(
    linhas: list[dict], valores: dict[tuple[str, str], float], ano: int
) -> dict[str, float]:
    todos = meses_do_ano(ano)
    return {
        l["id"]: round(sum(_num(valores.get((l["id"], m), 0)) for m in todos), 2)
        for l in linhas
    }


# --------------------------------------------------------------------------
# Realizado a partir dos gastos já lançados
# --------------------------------------------------------------------------

def realizado_dos_gastos(gastos: list[dict]) -> dict[str, dict]:
    """Agrega os gastos reais por mês e, dentro do mês, por cartão.

    O mês de um gasto de cartão é o da FATURA, não o da compra: é assim que o
    dinheiro sai da conta, e é assim que a planilha sempre tratou. Gasto de
    Pix/dinheiro/débito usa a própria data.
    """
    saida: dict[str, dict] = {}
    for g in gastos:
        if g.get("origem") == "cartao" and g.get("fatura_referencia"):
            mes = str(g["fatura_referencia"])[:7]
        else:
            mes = str(g.get("data", ""))[:7]
        if len(mes) != 7:
            continue

        bucket = saida.setdefault(mes, {"total": 0.0, "cartoes": {}})
        valor = _num(g.get("valor"))
        bucket["total"] = round(bucket["total"] + valor, 2)

        cartao = g.get("cartao")
        if cartao:
            bucket["cartoes"][cartao] = round(bucket["cartoes"].get(cartao, 0.0) + valor, 2)
    return saida


# --------------------------------------------------------------------------
# Linhas padrão — as mesmas da planilha
# --------------------------------------------------------------------------

LINHAS_PADRAO: tuple[tuple[str, str], ...] = (
    ("receita", "Salário / Renda Principal"),
    ("receita", "Outras Receitas"),
    ("fixa", "Moradia (Aluguel / Condomínio)"),
    ("fixa", "Energia Elétrica"),
    ("fixa", "Água / Esgoto"),
    ("fixa", "Internet"),
    ("fixa", "Telefone / Celular"),
    ("fixa", "PIC"),
    ("fixa", "Educação / Escola"),
    ("fixa", "Plano de Saúde"),
    ("fixa", "Transporte / Combustível"),
    ("fixa", "IPTU"),
    ("fixa", "Seguros"),
    ("fixa", "Prestação carro"),
    ("fixa", "Outras Despesas Fixas"),
    ("cartao", "Amex"),
    ("cartao", "Itaú Azul"),
    ("cartao", "Itaú Latam"),
    ("cartao", "Itaú Personalité"),
    ("cartao", "Itaú Azul (Esposa)"),
    ("cartao", "Itaú Personalité (Esposa)"),
)
