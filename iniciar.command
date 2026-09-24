#!/bin/bash
# =============================================================================
# Meus Gastos — iniciar no Mac
#
# Clique duas vezes neste arquivo no Finder, ou rode ./iniciar.command
#
# Na primeira vez: cria o ambiente, instala as dependências, gera o .env e
# pergunta o PIN. Nas próximas: só sobe o servidor, em segundos.
# Para parar: Ctrl+C nesta janela.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

VERDE=$'\033[0;32m'; AMARELO=$'\033[0;33m'; VERMELHO=$'\033[0;31m'; FIM=$'\033[0m'
ok()    { echo "${VERDE}✓${FIM} $1"; }
aviso() { echo "${AMARELO}!${FIM} $1"; }
erro()  { echo "${VERMELHO}✗ $1${FIM}" >&2; }

morrer() { erro "$1"; echo; echo "Pressione Enter para fechar."; read -r; exit 1; }

echo
echo "  Meus Gastos — controle de gastos pessoais"
echo "  ─────────────────────────────────────────"
echo

# --- 1. Python -------------------------------------------------------------
command -v python3 >/dev/null 2>&1 || morrer \
  "Python 3 não encontrado. Instale com:  brew install python"

PY_VER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
python3 - <<'EOF' || morrer "Python $(python3 -V) é antigo demais. Precisa de 3.9+. Instale com: brew install python"
import sys
sys.exit(0 if sys.version_info >= (3, 9) else 1)
EOF
ok "Python $PY_VER"

# --- 2. Ambiente virtual ---------------------------------------------------
if [ ! -d .venv ]; then
  echo "  Criando o ambiente (só na primeira vez)…"
  python3 -m venv .venv || morrer "Falhou ao criar o ambiente virtual."
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# Reinstala só quando o requirements.txt muda — nas próximas vezes pula.
MARCA=.venv/.requirements.sha
ATUAL=$(shasum -a 256 requirements.txt 2>/dev/null | cut -d' ' -f1 \
        || sha256sum requirements.txt | cut -d' ' -f1)
if [ ! -f "$MARCA" ] || [ "$(cat "$MARCA")" != "$ATUAL" ]; then
  echo "  Instalando dependências (leva 1–2 min na primeira vez)…"
  pip install --quiet --upgrade pip
  pip install --quiet -r requirements.txt openpyxl || morrer "Falhou ao instalar as dependências."
  echo "$ATUAL" > "$MARCA"
  ok "Dependências instaladas"
else
  ok "Dependências já instaladas"
fi

# --- 3. Configuração -------------------------------------------------------
if [ ! -f .env ]; then
  echo
  echo "  Primeira configuração."
  printf "  Escolha um PIN de 4 a 8 dígitos para abrir o app: "
  read -r PIN
  while ! printf '%s' "$PIN" | grep -Eq '^[0-9]{4,8}$'; do
    printf "  ${AMARELO}Só dígitos, de 4 a 8.${FIM} Tente de novo: "
    read -r PIN
  done

  CHAVE=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
  cat > .env <<EOF
# Gerado por iniciar.command. Este arquivo não vai para o GitHub.
SECRET_KEY=$CHAVE
APP_PIN=$PIN

# Banco local (SQLite). Deixe SUPABASE_URL vazio para rodar offline no Mac.
SQLITE_PATH=financas.sqlite3
SUPABASE_URL=
SUPABASE_SERVICE_KEY=

# Opcional: habilita ler recibo por foto. Sem isso, o resto funciona igual.
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-opus-5

PORT=5000
EOF
  chmod 600 .env
  ok "Configuração salva em .env (PIN: $PIN)"
else
  ok "Configuração encontrada (.env)"
fi

# --- 4. Planilha -----------------------------------------------------------
# Só na primeira vez: se houver um .xlsx aqui e o orçamento estiver vazio.
PLANILHA=$(ls -1 ./*.xlsx 2>/dev/null | grep -v '^\./~\$' | head -1 || true)
if [ -n "$PLANILHA" ]; then
  VAZIO=$(python3 - <<'EOF' 2>/dev/null || echo "erro"
from app.repo import get_repo
print("sim" if not get_repo().listar_linhas_orcamento() else "nao")
EOF
)
  if [ "$VAZIO" = "sim" ]; then
    echo "  Encontrei a planilha $(basename "$PLANILHA") — importando o orçamento…"
    python3 scripts/importar_planilha.py "$PLANILHA" | tail -1
  fi
fi

# --- 5. Subir --------------------------------------------------------------
PORTA=$(grep -E '^PORT=' .env | cut -d= -f2)
PORTA=${PORTA:-5000}

# Porta ocupada? Provavelmente é uma janela antiga ainda aberta.
if lsof -nP -iTCP:"$PORTA" -sTCP:LISTEN >/dev/null 2>&1; then
  aviso "A porta $PORTA já está em uso — o app talvez já esteja aberto."
  aviso "Feche a outra janela (Ctrl+C) ou mude PORT no .env."
  echo
fi

IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)

echo
echo "  ─────────────────────────────────────────"
echo "  No Mac:     http://localhost:$PORTA"
[ -n "$IP" ] && echo "  No celular: http://$IP:$PORTA   (mesma rede Wi-Fi)"
echo "  ─────────────────────────────────────────"
echo "  Para parar: Ctrl+C"
echo

# Abre o navegador quando o servidor responder.
( for _ in $(seq 1 40); do
    if curl -s -o /dev/null "http://127.0.0.1:$PORTA/login" 2>/dev/null; then
      command -v open >/dev/null 2>&1 && open "http://localhost:$PORTA"
      break
    fi
    sleep 0.5
  done ) &

exec python3 run.py
