"""Parser da fatura do cartão Itaú.

Regra de ouro: a fatura JÁ traz a categoria impressa em cada lançamento.
Aproveitamos essa categoria em vez de adivinhar por palavra-chave — a IA só
entra como fallback, e só quando a categoria não veio na linha.

Este módulo é regra pura: entra texto, sai estrutura. Sem I/O, sem rede.
Testado em tests/test_itau_fatura.py.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import date

from app.categorias import CATEGORIAS, normalizar_categoria, sem_acento

# --------------------------------------------------------------------------
# Blocos léxicos
# --------------------------------------------------------------------------

# 1.234,56 | 1234,56 | -12,90 | R$ 99,00
# O prefixo é "R$" ou "$" inteiro, nunca um "R" solto: com `R?` o parser comia
# a última letra do estabelecimento ("OPENAI *CHATGPT SUBSCR 20,00" perdia o R).
_VALOR = r"-?\s*(?:R\$|\$)?\s*\d{1,3}(?:\.\d{3})*,\d{2}"
RE_VALOR = re.compile(_VALOR)
RE_DATA = re.compile(r"^(\d{2})/(\d{2})(?:/(\d{2,4}))?\b")

# As categorias como o Itaú imprime (com acento ou sem).
_CATS_IMPRESSAS = sorted(
    {
        "supermercado", "restaurante", "lazer", "saude", "saúde", "viagem",
        "outros", "servicos", "serviços", "vestuario", "vestuário",
        "educacao", "educação", "government",
    },
    key=len,
    reverse=True,
)
RE_CATEGORIA_FIM = re.compile(
    r"\s+(" + "|".join(_CATS_IMPRESSAS) + r")\s*$", re.IGNORECASE
)

# "03/10", "PARC 03/10", "PARCELA 3 DE 10"
RE_PARCELA = re.compile(
    r"(?:parc(?:ela)?\.?\s*)?\b(\d{1,2})\s*(?:/|\s+de\s+)\s*(\d{1,2})\b",
    re.IGNORECASE,
)
RE_PRINCIPAL_JUROS = re.compile(
    r"principal[^0-9\-]{0,12}(" + _VALOR + r").{0,40}?juros[^0-9\-]{0,12}(" + _VALOR + r")",
    re.IGNORECASE | re.DOTALL,
)

# --------------------------------------------------------------------------
# Seções da fatura
# --------------------------------------------------------------------------

SECAO_COMPRAS = "compras"
SECAO_INTERNACIONAL = "internacional"
SECAO_PRODUTOS = "produtos_servicos"
SECAO_PARCELAS_FUTURAS = "parcelas_futuras"
SECAO_IGNORAR = "ignorar"

_MARCADORES = (
    # (trecho normalizado que abre a seção, seção)
    ("lancamentos: compras e saques", SECAO_COMPRAS),
    ("lancamentos compras e saques", SECAO_COMPRAS),
    ("compras e saques", SECAO_COMPRAS),
    ("lancamentos internacionais", SECAO_INTERNACIONAL),
    ("lancamentos: internacionais", SECAO_INTERNACIONAL),
    ("lancamentos: produtos e servicos", SECAO_PRODUTOS),
    ("lancamentos produtos e servicos", SECAO_PRODUTOS),
    ("produtos e servicos", SECAO_PRODUTOS),
    ("compras parceladas - proximas faturas", SECAO_PARCELAS_FUTURAS),
    ("compras parceladas proximas faturas", SECAO_PARCELAS_FUTURAS),
    ("proximas faturas", SECAO_PARCELAS_FUTURAS),
    ("limites do seu cartao", SECAO_IGNORAR),
    ("pontos", SECAO_IGNORAR),
)

# Linhas que nunca são gasto.
_RUIDO = (
    "pagamento efetuado", "pagamento em", "pgto debito conta", "pagto",
    "saldo anterior", "saldo em", "total desta fatura", "total da fatura",
    "subtotal", "limite total", "limite disponivel", "credito rotativo contratado",
    "demonstrativo", "nao ha lancamentos", "valor total", "data de vencimento",
)

# Indícios de juros / encargos evitáveis.
_TERMOS_JUROS = (
    "juros", "encargo", "rotativo", "mora", "multa", "parcelamento de fatura",
    "financiamento", "credito parcelado", "iof",
)


# --------------------------------------------------------------------------
# Estruturas
# --------------------------------------------------------------------------

@dataclass
class Lancamento:
    data: str                       # ISO yyyy-mm-dd
    estabelecimento: str
    valor: float
    categoria: str
    origem: str = "cartao"
    fatura_referencia: str = ""     # "2026-07"
    tem_juros: bool = False
    valor_juros: float | None = None
    criado_via: str = "import_fatura"
    observacoes: str | None = None
    parcela_atual: int | None = None
    parcela_total: int | None = None
    moeda_origem: str | None = None
    valor_origem: float | None = None
    categoria_incerta: bool = False  # True => candidato ao fallback de IA
    hash_dedupe: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("categoria_incerta", None)
        return d


@dataclass
class ParcelaFutura:
    descricao: str
    parcela_atual: int | None
    parcela_total: int | None
    valor_parcela: float
    valor_restante: float | None = None


@dataclass
class ResumoFatura:
    referencia: str = ""
    total: float | None = None
    vencimento: str | None = None
    limite_total: float | None = None
    encargos: float | None = None


@dataclass
class FaturaParseada:
    resumo: ResumoFatura = field(default_factory=ResumoFatura)
    lancamentos: list[Lancamento] = field(default_factory=list)
    parcelas_futuras: list[ParcelaFutura] = field(default_factory=list)
    linhas_ignoradas: list[str] = field(default_factory=list)

    @property
    def total_extraido(self) -> float:
        return round(sum(l.valor for l in self.lancamentos), 2)

    @property
    def total_juros(self) -> float:
        return round(sum(l.valor_juros or 0.0 for l in self.lancamentos), 2)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def parse_valor(bruto: str) -> float:
    """'1.234,56' -> 1234.56 ; '-R$ 12,90' -> -12.9"""
    texto = bruto.strip()
    negativo = texto.startswith("-") or texto.endswith("-")
    limpo = re.sub(r"[^\d,.-]", "", texto).lstrip("-").rstrip("-")
    limpo = limpo.replace(".", "").replace(",", ".")
    try:
        valor = float(limpo)
    except ValueError:
        return 0.0
    return -valor if negativo else valor


def _norm(linha: str) -> str:
    return re.sub(r"\s+", " ", sem_acento(linha).lower()).strip()


def _resolver_ano(dia: int, mes: int, ref_ano: int, ref_mes: int) -> date:
    """A fatura traz só DD/MM. Um mês maior que o de referência é do ano anterior."""
    ano = ref_ano
    if mes > ref_mes + 1:          # ex.: ref 01/2026 e lançamento 12/.. => 2025
        ano = ref_ano - 1
    elif mes == 12 and ref_mes <= 2:
        ano = ref_ano - 1
    try:
        return date(ano, mes, dia)
    except ValueError:             # 31/02 e afins vindos de OCR ruim
        return date(ano, mes, 1)


def _hash(referencia: str, iso: str, estab: str, valor: float, ordem: int) -> str:
    """Idempotência de importação: reimportar a mesma fatura não duplica nada.

    A ordem entra no hash porque a mesma compra pode aparecer duas vezes no
    mesmo dia, pelo mesmo valor, no mesmo lugar — e isso é legítimo.
    """
    bruto = f"{referencia}|{iso}|{_norm(estab)}|{valor:.2f}|{ordem}"
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:32]


def _detecta_secao(linha_norm: str) -> str | None:
    for marcador, secao in _MARCADORES:
        if marcador in linha_norm:
            return secao
    return None


def _eh_ruido(linha_norm: str) -> bool:
    return any(r in linha_norm for r in _RUIDO)


def _extrai_parcela(descricao: str) -> tuple[int | None, int | None]:
    m = RE_PARCELA.search(descricao)
    if not m:
        return None, None
    atual, total = int(m.group(1)), int(m.group(2))
    # "12/10" não é parcela; datas coladas na descrição confundem.
    if total == 0 or atual == 0 or atual > total or total > 48:
        return None, None
    return atual, total


def _limpa_estabelecimento(texto: str) -> str:
    texto = re.sub(r"\s+", " ", texto).strip(" .-\t")
    texto = re.sub(r"^\d{2}/\d{2}\s*", "", texto)
    return texto[:120]


# --------------------------------------------------------------------------
# Parser principal
# --------------------------------------------------------------------------

def _referencia_do_texto(texto: str) -> tuple[str | None, str | None]:
    """Descobre a referência (yyyy-mm) e o vencimento a partir do cabeçalho."""
    m = re.search(
        r"vencimento[^0-9]{0,20}(\d{2})/(\d{2})/(\d{2,4})", sem_acento(texto), re.IGNORECASE
    )
    if m:
        dia, mes, ano = int(m.group(1)), int(m.group(2)), int(m.group(3))
        ano = ano + 2000 if ano < 100 else ano
        try:
            venc = date(ano, mes, dia)
            return f"{ano:04d}-{mes:02d}", venc.isoformat()
        except ValueError:
            pass
    meses = {
        "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5,
        "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
        "novembro": 11, "dezembro": 12,
    }
    m = re.search(
        r"\b(" + "|".join(meses) + r")\s*(?:de\s*)?(\d{4})\b", sem_acento(texto).lower()
    )
    if m:
        return f"{int(m.group(2)):04d}-{meses[m.group(1)]:02d}", None
    return None, None


def _valor_rotulado(texto: str, *rotulos: str) -> float | None:
    for rot in rotulos:
        m = re.search(
            re.escape(rot) + r"[^0-9\-]{0,40}(" + _VALOR + r")",
            sem_acento(texto),
            re.IGNORECASE,
        )
        if m:
            return parse_valor(m.group(1))
    return None


def parse_fatura(texto: str, referencia: str | None = None) -> FaturaParseada:
    """Converte o texto extraído do PDF da fatura em lançamentos estruturados.

    `referencia` ("yyyy-mm") pode ser forçada pelo usuário na tela de import;
    se vier vazia, é lida do cabeçalho da própria fatura.
    """
    fatura = FaturaParseada()
    ref_detectada, vencimento = _referencia_do_texto(texto)
    referencia = referencia or ref_detectada or date.today().strftime("%Y-%m")
    ref_ano, ref_mes = int(referencia[:4]), int(referencia[5:7])

    fatura.resumo = ResumoFatura(
        referencia=referencia,
        vencimento=vencimento,
        total=_valor_rotulado(texto, "total desta fatura", "total da fatura", "valor total da fatura"),
        limite_total=_valor_rotulado(texto, "limite total de credito", "limite total"),
        encargos=_valor_rotulado(texto, "total de encargos", "encargos cobrados", "juros do periodo"),
    )

    secao = SECAO_COMPRAS
    ordem = 0

    for linha_bruta in texto.splitlines():
        linha = linha_bruta.rstrip()
        if not linha.strip():
            continue
        linha_norm = _norm(linha)

        nova_secao = _detecta_secao(linha_norm)
        if nova_secao:
            secao = nova_secao
            continue

        if secao == SECAO_IGNORAR or _eh_ruido(linha_norm):
            continue

        if secao == SECAO_PARCELAS_FUTURAS:
            pf = _parse_parcela_futura(linha)
            if pf:
                fatura.parcelas_futuras.append(pf)
            continue

        lanc = _parse_linha_lancamento(linha, secao, referencia, ref_ano, ref_mes)
        if lanc is None:
            if RE_DATA.match(linha.strip()):
                fatura.linhas_ignoradas.append(linha.strip())
            continue

        ordem += 1
        lanc.hash_dedupe = _hash(referencia, lanc.data, lanc.estabelecimento, lanc.valor, ordem)
        fatura.lancamentos.append(lanc)

    _fundir_principal_juros(fatura)
    return fatura


def _parse_linha_lancamento(
    linha: str, secao: str, referencia: str, ref_ano: int, ref_mes: int
) -> Lancamento | None:
    texto = linha.strip()
    m_data = RE_DATA.match(texto)
    if not m_data:
        return None

    dia, mes = int(m_data.group(1)), int(m_data.group(2))
    if not (1 <= mes <= 12 and 1 <= dia <= 31):
        return None

    if m_data.group(3):
        ano = int(m_data.group(3))
        ano = ano + 2000 if ano < 100 else ano
        try:
            dt = date(ano, mes, dia)
        except ValueError:
            dt = _resolver_ano(dia, mes, ref_ano, ref_mes)
    else:
        dt = _resolver_ano(dia, mes, ref_ano, ref_mes)

    resto = texto[m_data.end():].strip()
    valores = RE_VALOR.findall(resto)
    if not valores:
        return None

    if secao == SECAO_INTERNACIONAL and len(valores) >= 2:
        # DATA | ESTABELECIMENTO | US$ | R$ — o que vale é o último (R$).
        valor_origem = parse_valor(valores[-2])
        valor = parse_valor(valores[-1])
        corte = resto.rfind(valores[-2])
        descricao = _limpa_estabelecimento(resto[:corte])
        moeda = "USD"
    else:
        valor = parse_valor(valores[-1])
        corte = resto.rfind(valores[-1])
        descricao = _limpa_estabelecimento(resto[:corte])
        valor_origem, moeda = None, None

    if not descricao or valor == 0:
        return None

    # Categoria: primeiro a que o Itaú imprimiu no fim da linha.
    incerta = False
    m_cat = RE_CATEGORIA_FIM.search(descricao)
    if m_cat:
        categoria = normalizar_categoria(m_cat.group(1))
        descricao = _limpa_estabelecimento(descricao[: m_cat.start()])
    elif secao == SECAO_PRODUTOS:
        # A seção já diz a natureza do lançamento (Pix, boleto, parcelamento
        # feito no cartão). Não precisa gastar chamada de IA com isso.
        categoria = "servicos"
    else:
        categoria = "outros"
        incerta = True

    if not descricao:
        return None

    desc_norm = _norm(descricao)
    tem_juros = any(t in desc_norm for t in _TERMOS_JUROS)
    valor_juros = None

    m_pj = RE_PRINCIPAL_JUROS.search(resto)
    if m_pj:
        valor_juros = parse_valor(m_pj.group(2))
        tem_juros = True
    elif tem_juros and re.search(r"\bjuros\b|\bencargo", desc_norm):
        # Linha que É o juros (não a compra) — o valor inteiro é juros.
        valor_juros = valor

    parcela_atual, parcela_total = _extrai_parcela(descricao)

    return Lancamento(
        data=dt.isoformat(),
        estabelecimento=descricao,
        valor=valor,
        categoria=categoria,
        origem="cartao",
        fatura_referencia=referencia,
        tem_juros=tem_juros,
        valor_juros=round(valor_juros, 2) if valor_juros else None,
        criado_via="import_fatura",
        parcela_atual=parcela_atual,
        parcela_total=parcela_total,
        moeda_origem=moeda,
        valor_origem=valor_origem,
        categoria_incerta=incerta,
    )


def _parse_parcela_futura(linha: str) -> ParcelaFutura | None:
    texto = linha.strip()
    valores = RE_VALOR.findall(texto)
    if not valores:
        return None
    if _eh_ruido(_norm(texto)):
        return None
    # Corta a partir do PRIMEIRO valor da linha: "LATAM 02/06 1.649,20 412,30"
    # deve virar "LATAM 02/06", não arrastar os dois montantes para o nome.
    primeiro = RE_VALOR.search(texto)
    descricao = _limpa_estabelecimento(texto[: primeiro.start()])
    if not descricao or len(descricao) < 3:
        return None
    atual, total = _extrai_parcela(descricao)
    return ParcelaFutura(
        descricao=descricao,
        parcela_atual=atual,
        parcela_total=total,
        valor_parcela=parse_valor(valores[-1]),
        valor_restante=parse_valor(valores[-2]) if len(valores) >= 2 else None,
    )


def _fundir_principal_juros(fatura: FaturaParseada) -> None:
    """Itaú às vezes quebra o parcelamento em duas linhas: Principal e Juros.

    Duas linhas viram uma: o gasto carrega o principal e o juros embutido.
    Sem isso, o total do mês conta o mesmo dinheiro duas vezes.
    """
    juntar: list[int] = []
    for i, lanc in enumerate(fatura.lancamentos):
        desc = _norm(lanc.estabelecimento)
        if not re.search(r"\bjuros\b", desc):
            continue
        base = re.sub(r"[-–]?\s*juros.*$", "", desc).strip()
        for j in range(i - 1, max(-1, i - 4), -1):
            anterior = fatura.lancamentos[j]
            desc_ant = _norm(anterior.estabelecimento)
            desc_ant_base = re.sub(r"[-–]?\s*principal.*$", "", desc_ant).strip()
            if base and desc_ant_base.startswith(base[: max(8, len(base) // 2)]):
                anterior.tem_juros = True
                anterior.valor_juros = round((anterior.valor_juros or 0) + lanc.valor, 2)
                anterior.valor = round(anterior.valor + lanc.valor, 2)
                anterior.estabelecimento = _limpa_estabelecimento(
                    re.sub(r"[-–]?\s*principal.*$", "", anterior.estabelecimento, flags=re.I)
                ) or anterior.estabelecimento
                juntar.append(i)
                break
    for i in reversed(juntar):
        fatura.lancamentos.pop(i)
