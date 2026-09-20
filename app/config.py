"""Configuração central. Tudo vem de variáveis de ambiente (.env)."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "sim"}


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-inseguro-troque")
    APP_PIN = os.getenv("APP_PIN", "").strip()

    SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "").strip()

    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
    ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5").strip()

    SQLITE_PATH = os.getenv("SQLITE_PATH", "financas.sqlite3")

    # Upload: foto de recibo. 12 MB cobre foto de celular sem folga absurda.
    MAX_CONTENT_LENGTH = 12 * 1024 * 1024

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("COOKIE_SECURE", False)
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 30  # 30 dias: é o celular do dono

    @classmethod
    def usa_supabase(cls) -> bool:
        return bool(cls.SUPABASE_URL and cls.SUPABASE_SERVICE_KEY)

    @classmethod
    def tem_claude(cls) -> bool:
        return bool(cls.ANTHROPIC_API_KEY)
