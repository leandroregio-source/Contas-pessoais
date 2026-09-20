"""Fábrica do repositório: Supabase quando configurado, SQLite caso contrário."""
from __future__ import annotations

from app.config import Config
from app.repo.base import CAMPOS_EDITAVEIS, CAMPOS_GASTO, Repo
from app.repo.sqlite_repo import SQLiteRepo

_instancia: Repo | None = None


def get_repo() -> Repo:
    global _instancia
    if _instancia is None:
        if Config.usa_supabase():
            from app.repo.supabase_repo import SupabaseRepo

            _instancia = SupabaseRepo(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)
        else:
            _instancia = SQLiteRepo(Config.SQLITE_PATH)
    return _instancia


def reset_repo() -> None:
    """Usado pelos testes para trocar o backend entre casos."""
    global _instancia
    _instancia = None


__all__ = ["get_repo", "reset_repo", "Repo", "CAMPOS_GASTO", "CAMPOS_EDITAVEIS"]
