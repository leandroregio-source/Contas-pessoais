# Meus Gastos — PWA de controle de gastos pessoais

App pessoal (single-user) para registrar e analisar todos os gastos: **fatura do
cartão Itaú (PDF)**, **Pix**, **débito** e **dinheiro** — agrupando por categoria,
comparando mês a mês e apontando onde dá para economizar.

Projeto **isolado**: não tem nenhuma relação com sistemas de laboratório/ERP.
Banco Supabase próprio, credenciais próprias.

```
Celular (PWA)  ──►  Flask  ──►  Supabase (Postgres + RLS)
                      │
                      └──►  API da Anthropic  (só foto de recibo e
                                                fallback de categoria)
```

---

## O que ele faz

| Tela | O que resolve |
|---|---|
| **Resumo** | Total do mês, variação contra o mês anterior, evolução de 6 meses, gasto por categoria, maiores gastos |
| **Foto** | Fotografa a nota/recibo → Claude lê → você confere → salva. Também lança manual |
| **Fatura** | Sobe o PDF da fatura do Itaú → prévia editável → confirma. Reimportar não duplica |
| **Histórico** | Todos os lançamentos, filtráveis por período, categoria, origem e busca |
| **Insights** | Sugestões de economia, juros pagos, assinaturas recorrentes, categorias em alta, parcelas já comprometidas |

### Duas decisões que definem o app

**1. A fatura do Itaú é lida por regex, não por IA.** A fatura já imprime a
categoria em cada lançamento (`supermercado`, `restaurante`, `saúde`…). Usar
essa categoria é mais rápido, mais barato e mais confiável do que adivinhar por
palavra-chave ou mandar tudo para um modelo. Numa fatura de 13 lançamentos,
tipicamente 11 saem prontos e só 2 chegam à IA — e esses 2 vão **numa única
chamada em lote**, nunca uma por linha.

**2. Nada é salvo sem conferência.** Foto e fatura sempre passam por uma tela de
revisão. Leitura errada salva em silêncio é pior que leitura que falha.

### Juros em destaque

Pix parcelado e parcelamento de fatura vêm com juros embutidos. O parser
identifica os dois formatos que o Itaú usa (`Principal (R$ X) + Juros (R$ Y)` na
mesma linha, ou em duas linhas seguidas — que são **fundidas em um lançamento só**,
senão o mês contaria o mesmo dinheiro duas vezes) e acumula o total pago em
juros no mês e no ano.

---

## Rodando

```bash
git clone <este-repo> && cd financas-pessoais
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env     # preencha (veja abaixo)
python run.py            # http://localhost:5000
```

Sem `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` o app usa **SQLite local**
(`financas.sqlite3`) automaticamente. Serve para experimentar antes de criar o
projeto no Supabase.

### Variáveis (`.env`)

| Variável | Para quê |
|---|---|
| `SECRET_KEY` | Assina o cookie de sessão. `python -c "import secrets;print(secrets.token_hex(32))"` |
| `APP_PIN` | PIN de acesso (4–8 dígitos). **Vazio = app aberto**, só para dev |
| `SUPABASE_URL` | `https://xxxx.supabase.co` do seu projeto |
| `SUPABASE_SERVICE_KEY` | Chave `service_role`. **Só no servidor, nunca no front** |
| `ANTHROPIC_API_KEY` | Habilita a leitura de recibo por foto. Sem ela, o resto funciona normal |
| `ANTHROPIC_MODEL` | Padrão `claude-opus-5` |
| `COOKIE_SECURE` | `1` quando servir por HTTPS |

### Supabase

1. Crie um projeto pessoal novo (o plano gratuito basta).
2. Rode `supabase/schema.sql` inteiro no **SQL Editor**.
3. Copie a URL e a chave `service_role` (Settings → API) para o `.env`.

O schema cria `gastos`, `faturas` e `parcelas_futuras` com índices e
**RLS ligada sem nenhuma policy** — mais os `GRANT`s revogados de `anon` e
`authenticated`. Traduzindo: mesmo que a chave pública vaze, ela lê zero linha.
Quem opera o banco é só o servidor, com a `service_role`. Quem autentica a
pessoa é o PIN do Flask.

### Instalar no celular

Abra a URL no navegador do celular → **Adicionar à tela de início**. Vira app
com ícone próprio, tela cheia e acesso à câmera. Para usar fora de casa é
preciso servir por HTTPS (o service worker e a câmera exigem contexto seguro) —
um túnel (Cloudflare Tunnel, Tailscale) ou qualquer PaaS resolve:

```bash
gunicorn -w 2 -b 0.0.0.0:8000 run:app
```

---

## Estrutura

```
app/
  config.py              variáveis de ambiente
  auth.py                PIN, tempo constante, trava por tentativas
  api.py                 rotas JSON (/api/*)
  views.py               páginas (app shell + login)
  categorias.py          as 10 categorias fixas e seus sinônimos
  repo/                  persistência: supabase_repo.py | sqlite_repo.py
  services/
    itau_fatura.py       parser da fatura           ← regra pura, testada
    analytics.py         agregações e sugestões     ← regra pura, testada
    normalize.py         validação de entrada       ← regra pura, testada
    pdf_text.py          PDF → texto (pdfplumber)
    claude_extract.py    visão (recibo) + categoria em lote
static/
  js/{app,api,screens,charts}.js    ES modules, sem framework
  css/app.css            tokens de cor, claro e escuro
  sw.js                  service worker
supabase/schema.sql
tests/                   47 testes, sem rede
```

**Toda regra de negócio vive em `app/services/*` como função pura** — recebe
dados, devolve dados, não toca em rede nem banco. É o que permite os 47 testes
rodarem em 0,3 s e o que mantém a lógica verificável.

```bash
python -m pytest tests/ -q
```

### Sobre o front

Sem framework, sem CDN, sem bundler. Motivos concretos: a CSP é restritiva
(`default-src 'self'`), o app precisa abrir offline, e num celular o custo de
1 MB de JavaScript aparece. Os gráficos são `<canvas>` desenhado à mão — barras,
não pizza: são até 10 categorias ordenadas por valor, e barra horizontal se lê
num aparelho estreito, pizza não. Série única por gráfico, então uma cor só e
nenhuma legenda; a identidade vem do rótulo ao lado da barra. Variação vem
sempre com **seta + número**, nunca só com a cor.

O service worker guarda a casca do app (cache-first) mas **nunca** `/api/*`:
dado financeiro velho servido do cache é pior que erro de conexão.

---

## Notas de segurança

- Nenhuma chave no código. Tudo em `.env`, que está no `.gitignore`.
- `service_role` só no servidor; o front nunca fala com o Supabase direto.
- RLS ligada + `GRANT` revogado: dupla tranca.
- PIN comparado em tempo constante, com bloqueio após 5 tentativas em 5 min.
- CSP, `X-Frame-Options: DENY`, `nosniff` e cookie `HttpOnly`/`SameSite=Lax`.
- A API só aceita os campos que conhece — payload não injeta coluna no banco
  (há teste para isso).
