"""Backend Supabase via PostgREST.

Fala HTTP direto com a API REST do Supabase usando a service_role key — que
NUNCA sai do servidor. As policies de RLS bloqueiam anon/authenticated por
completo (ver supabase/schema.sql): quem autentica o usuário é o PIN do Flask,
e o Postgres só aceita este processo.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import requests

from app.repo.base import CAMPOS_EDITAVEIS

TIMEOUT = 20


class SupabaseError(RuntimeError):
    pass


class SupabaseRepo:
    def __init__(self, url: str, service_key: str):
        self.base = f"{url.rstrip('/')}/rest/v1"
        self.sessao = requests.Session()
        self.sessao.headers.update(
            {
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    # -- transporte --------------------------------------------------------
    def _req(self, metodo: str, caminho: str, **kw):
        resp = self.sessao.request(
            metodo, f"{self.base}{caminho}", timeout=TIMEOUT, **kw
        )
        if resp.status_code >= 400:
            raise SupabaseError(
                f"Supabase {resp.status_code} em {metodo} {caminho}: {resp.text[:400]}"
            )
        if resp.status_code == 204 or not resp.content:
            return []
        return resp.json()

    # -- gastos ------------------------------------------------------------
    def inserir_gastos(self, gastos: list[dict]) -> dict:
        """Insere ignorando duplicados por hash_dedupe.

        `resolution=ignore-duplicates` faz a reimportação da mesma fatura ser
        idempotente numa única ida ao banco, em vez de um SELECT por linha.
        """
        if not gastos:
            return {"inseridos": 0, "duplicados": 0}
        agora = datetime.now(timezone.utc).isoformat()
        payload = []
        for g in gastos:
            linha = dict(g)
            linha.setdefault("id", str(uuid.uuid4()))
            linha.setdefault("criado_em", agora)
            linha["tem_juros"] = bool(linha.get("tem_juros"))
            payload.append(linha)

        criados = self._req(
            "POST",
            "/gastos?on_conflict=hash_dedupe",
            json=payload,
            headers={"Prefer": "return=representation,resolution=ignore-duplicates"},
        )
        inseridos = len(criados)
        return {"inseridos": inseridos, "duplicados": len(payload) - inseridos}

    def listar_gastos(
        self, desde=None, ate=None, categoria=None, origem=None, busca=None, limite=5000
    ) -> list[dict]:
        params: dict[str, str] = {
            "select": "*",
            "order": "data.desc,criado_em.desc",
            "limit": str(limite),
        }
        if desde:
            params["data"] = f"gte.{desde}"
        if ate:
            # PostgREST não repete chave: o intervalo vai via and=()
            params.pop("data", None)
            faixa = [f"data.gte.{desde}"] if desde else []
            faixa.append(f"data.lte.{ate}")
            params["and"] = f"({','.join(faixa)})"
        if categoria:
            params["categoria"] = f"eq.{categoria}"
        if origem:
            params["origem"] = f"eq.{origem}"
        if busca:
            params["estabelecimento"] = f"ilike.*{busca}*"
        return self._req("GET", "/gastos", params=params)

    def obter_gasto(self, gasto_id: str) -> dict | None:
        linhas = self._req(
            "GET", "/gastos", params={"select": "*", "id": f"eq.{gasto_id}", "limit": "1"}
        )
        return linhas[0] if linhas else None

    def atualizar_gasto(self, gasto_id: str, campos: dict) -> dict | None:
        limpos = {k: v for k, v in campos.items() if k in CAMPOS_EDITAVEIS}
        if not limpos:
            return self.obter_gasto(gasto_id)
        linhas = self._req(
            "PATCH",
            "/gastos",
            params={"id": f"eq.{gasto_id}"},
            json=limpos,
            headers={"Prefer": "return=representation"},
        )
        return linhas[0] if linhas else None

    def remover_gasto(self, gasto_id: str) -> bool:
        linhas = self._req(
            "DELETE",
            "/gastos",
            params={"id": f"eq.{gasto_id}"},
            headers={"Prefer": "return=representation"},
        )
        return bool(linhas)

    # -- faturas -----------------------------------------------------------
    def salvar_fatura(self, resumo: dict, parcelas: list[dict]) -> None:
        ref = resumo.get("referencia")
        if not ref:
            return
        self._req(
            "POST",
            "/faturas?on_conflict=referencia",
            json=[
                {
                    "referencia": ref,
                    "total": resumo.get("total"),
                    "vencimento": resumo.get("vencimento"),
                    "limite_total": resumo.get("limite_total"),
                    "encargos": resumo.get("encargos"),
                    "importada_em": datetime.now(timezone.utc).isoformat(),
                }
            ],
            headers={"Prefer": "resolution=merge-duplicates"},
        )
        # Reimportar a fatura substitui as parcelas futuras daquela referência.
        self._req("DELETE", "/parcelas_futuras", params={"referencia": f"eq.{ref}"})
        if parcelas:
            self._req(
                "POST",
                "/parcelas_futuras",
                json=[
                    {
                        "id": str(uuid.uuid4()),
                        "referencia": ref,
                        "descricao": p.get("descricao"),
                        "parcela_atual": p.get("parcela_atual"),
                        "parcela_total": p.get("parcela_total"),
                        "valor_parcela": p.get("valor_parcela"),
                        "valor_restante": p.get("valor_restante"),
                    }
                    for p in parcelas
                ],
            )

    def listar_parcelas_futuras(self) -> list[dict]:
        return self._req(
            "GET",
            "/parcelas_futuras",
            params={"select": "*", "order": "valor_parcela.desc"},
        )

    def listar_faturas(self) -> list[dict]:
        return self._req(
            "GET", "/faturas", params={"select": "*", "order": "referencia.desc"}
        )

    def ping(self) -> bool:
        try:
            self._req("GET", "/gastos", params={"select": "id", "limit": "1"})
            return True
        except (SupabaseError, requests.RequestException):
            return False
