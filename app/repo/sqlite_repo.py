"""Backend SQLite — usado quando não há Supabase configurado.

Serve para rodar o app localmente e para os testes, sem depender de rede.
O schema espelha o do Supabase (supabase/schema.sql).
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from app.repo.base import CAMPOS_EDITAVEIS

_SCHEMA = """
CREATE TABLE IF NOT EXISTS gastos (
    id                TEXT PRIMARY KEY,
    data              TEXT NOT NULL,
    estabelecimento   TEXT NOT NULL,
    valor             REAL NOT NULL,
    categoria         TEXT NOT NULL DEFAULT 'outros',
    origem            TEXT NOT NULL DEFAULT 'cartao',
    fatura_referencia TEXT,
    tem_juros         INTEGER NOT NULL DEFAULT 0,
    valor_juros       REAL,
    criado_via        TEXT NOT NULL DEFAULT 'manual',
    observacoes       TEXT,
    parcela_atual     INTEGER,
    parcela_total     INTEGER,
    moeda_origem      TEXT,
    valor_origem      REAL,
    hash_dedupe       TEXT UNIQUE,
    criado_em         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gastos_data ON gastos(data DESC);
CREATE INDEX IF NOT EXISTS idx_gastos_categoria ON gastos(categoria);
CREATE INDEX IF NOT EXISTS idx_gastos_juros ON gastos(tem_juros) WHERE tem_juros = 1;

CREATE TABLE IF NOT EXISTS faturas (
    referencia   TEXT PRIMARY KEY,
    total        REAL,
    vencimento   TEXT,
    limite_total REAL,
    encargos     REAL,
    importada_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS parcelas_futuras (
    id             TEXT PRIMARY KEY,
    referencia     TEXT NOT NULL,
    descricao      TEXT NOT NULL,
    parcela_atual  INTEGER,
    parcela_total  INTEGER,
    valor_parcela  REAL NOT NULL,
    valor_restante REAL
);
"""


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteRepo:
    def __init__(self, caminho: str):
        self.caminho = caminho
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.caminho)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @staticmethod
    def _linha(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["tem_juros"] = bool(d.get("tem_juros"))
        return d

    # -- gastos ------------------------------------------------------------
    def inserir_gastos(self, gastos: list[dict]) -> dict:
        if not gastos:
            return {"inseridos": 0, "duplicados": 0}
        colunas = (
            "id", "data", "estabelecimento", "valor", "categoria", "origem",
            "fatura_referencia", "tem_juros", "valor_juros", "criado_via",
            "observacoes", "parcela_atual", "parcela_total", "moeda_origem",
            "valor_origem", "hash_dedupe", "criado_em",
        )
        sql = (
            f"INSERT OR IGNORE INTO gastos ({','.join(colunas)}) "
            f"VALUES ({','.join('?' * len(colunas))})"
        )
        inseridos = 0
        with self._conn() as conn:
            for g in gastos:
                linha = dict(g)
                linha.setdefault("id", str(uuid.uuid4()))
                linha.setdefault("criado_em", _agora())
                linha["tem_juros"] = 1 if linha.get("tem_juros") else 0
                cur = conn.execute(sql, [linha.get(c) for c in colunas])
                inseridos += cur.rowcount or 0
        return {"inseridos": inseridos, "duplicados": len(gastos) - inseridos}

    def listar_gastos(
        self, desde=None, ate=None, categoria=None, origem=None, busca=None, limite=5000
    ) -> list[dict]:
        filtros = [
            ("data >= ?", desde),
            ("data <= ?", ate),
            ("categoria = ?", categoria),
            ("origem = ?", origem),
            ("estabelecimento LIKE ?", f"%{busca}%" if busca else None),
        ]
        ativos = [(clausula, valor) for clausula, valor in filtros if valor]
        sql = "SELECT * FROM gastos"
        if ativos:
            sql += " WHERE " + " AND ".join(c for c, _ in ativos)
        sql += " ORDER BY data DESC, criado_em DESC LIMIT ?"
        args = [v for _, v in ativos] + [limite]
        with self._conn() as conn:
            return [self._linha(r) for r in conn.execute(sql, args)]

    def obter_gasto(self, gasto_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM gastos WHERE id = ?", (gasto_id,)).fetchone()
        return self._linha(row) if row else None

    def atualizar_gasto(self, gasto_id: str, campos: dict) -> dict | None:
        limpos = {k: v for k, v in campos.items() if k in CAMPOS_EDITAVEIS}
        if not limpos:
            return self.obter_gasto(gasto_id)
        if "tem_juros" in limpos:
            limpos["tem_juros"] = 1 if limpos["tem_juros"] else 0
        sets = ", ".join(f"{k} = ?" for k in limpos)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE gastos SET {sets} WHERE id = ?", [*limpos.values(), gasto_id]
            )
        return self.obter_gasto(gasto_id)

    def remover_gasto(self, gasto_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM gastos WHERE id = ?", (gasto_id,))
        return bool(cur.rowcount)

    # -- faturas -----------------------------------------------------------
    def salvar_fatura(self, resumo: dict, parcelas: list[dict]) -> None:
        ref = resumo.get("referencia")
        if not ref:
            return
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO faturas (referencia,total,vencimento,limite_total,encargos,importada_em)"
                " VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(referencia) DO UPDATE SET total=excluded.total,"
                " vencimento=excluded.vencimento, limite_total=excluded.limite_total,"
                " encargos=excluded.encargos, importada_em=excluded.importada_em",
                (
                    ref, resumo.get("total"), resumo.get("vencimento"),
                    resumo.get("limite_total"), resumo.get("encargos"), _agora(),
                ),
            )
            conn.execute("DELETE FROM parcelas_futuras WHERE referencia = ?", (ref,))
            conn.executemany(
                "INSERT INTO parcelas_futuras"
                " (id,referencia,descricao,parcela_atual,parcela_total,valor_parcela,valor_restante)"
                " VALUES (?,?,?,?,?,?,?)",
                [
                    (
                        str(uuid.uuid4()), ref, p.get("descricao"),
                        p.get("parcela_atual"), p.get("parcela_total"),
                        p.get("valor_parcela"), p.get("valor_restante"),
                    )
                    for p in parcelas
                ],
            )

    def listar_parcelas_futuras(self) -> list[dict]:
        with self._conn() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM parcelas_futuras ORDER BY valor_parcela DESC"
                )
            ]

    def listar_faturas(self) -> list[dict]:
        with self._conn() as conn:
            return [
                dict(r)
                for r in conn.execute("SELECT * FROM faturas ORDER BY referencia DESC")
            ]

    def ping(self) -> bool:
        try:
            with self._conn() as conn:
                conn.execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False
