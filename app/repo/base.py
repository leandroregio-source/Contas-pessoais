"""Contrato de persistência.

Duas implementações: Supabase (produção) e SQLite (dev/offline). O app só
conhece esta interface, então trocar o backend não toca em rota nenhuma.
"""
from __future__ import annotations

from typing import Protocol

CAMPOS_GASTO = (
    "id", "data", "estabelecimento", "valor", "categoria", "origem",
    "fatura_referencia", "tem_juros", "valor_juros", "criado_via",
    "observacoes", "parcela_atual", "parcela_total", "moeda_origem",
    "valor_origem", "hash_dedupe", "criado_em",
)

CAMPOS_EDITAVEIS = (
    "data", "estabelecimento", "valor", "categoria", "origem",
    "fatura_referencia", "tem_juros", "valor_juros", "observacoes",
    "parcela_atual", "parcela_total",
)


class Repo(Protocol):
    def inserir_gastos(self, gastos: list[dict]) -> dict: ...
    def listar_gastos(
        self,
        desde: str | None = None,
        ate: str | None = None,
        categoria: str | None = None,
        origem: str | None = None,
        busca: str | None = None,
        limite: int = 5000,
    ) -> list[dict]: ...
    def obter_gasto(self, gasto_id: str) -> dict | None: ...
    def atualizar_gasto(self, gasto_id: str, campos: dict) -> dict | None: ...
    def remover_gasto(self, gasto_id: str) -> bool: ...
    def salvar_fatura(self, resumo: dict, parcelas: list[dict]) -> None: ...
    def listar_parcelas_futuras(self) -> list[dict]: ...
    def listar_faturas(self) -> list[dict]: ...
    def ping(self) -> bool: ...
