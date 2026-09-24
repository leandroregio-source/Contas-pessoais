# Meus Gastos — PWA de controle de gastos pessoais

App pessoal (single-user) para registrar e analisar todos os gastos: **fatura do
cartão Itaú (PDF)**, **Pix**, **débito** e **dinheiro** — agrupando por categoria,
comparando mês a mês e apontando onde dá para economizar.

Projeto **isolado**: não tem nenhuma relação com sistemas de laboratório/ERP.
Dados próprios, credenciais próprias.

```
Navegador / celular (PWA)  ──►  Flask  ──►  SQLite no seu Mac      (padrão)
                                  │         ou Supabase/Postgres   (opcional)
                                  │
                                  └──►  API da Anthropic
                                        (só foto de recibo e fallback
                                         de categoria — o resto é regex)
```

Roda inteiro no seu Mac, sem nuvem e sem conta em lugar nenhum. O Supabase é
opcional, para quando você quiser os mesmos dados em mais de um aparelho.

---

## O que ele faz

| Tela | O que resolve |
|---|---|
| **Resumo** | Total do mês, variação contra o mês anterior, evolução de 6 meses, gasto por categoria, maiores gastos |
| **Foto** | Fotografa a nota/recibo → Claude lê → você confere → salva. Também lança manual |
| **Fatura** | Sobe o PDF da fatura do Itaú → prévia editável → confirma. Reimportar não duplica |
| **Orçamento** | O orçamento mensal da planilha, dentro do app: saldo, receitas, despesas fixas e cartões — com previsto **e** realizado |
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

### Orçamento: o que a planilha fazia, e o que ela não fazia

O modelo é o mesmo da planilha `Controle Financeiro Pessoal`:

```
   Saldo de Abertura        ← Saldo Final do mês anterior
(+) Receitas
(−) Despesas Fixas
(−) Cartões de Crédito
────────────────────────────
   Total de Saídas   = fixas + cartões
   Resultado do Mês  = receitas − saídas
   Saldo Final       = abertura + resultado   → abre o mês seguinte
```

O que muda é que cada linha passa a ter **previsto × realizado**. O previsto é
digitado, como na planilha. O realizado vem dos gastos que já estão no banco —
e nas linhas de cartão vem direto da fatura importada, valor exato, sem
redigitação. O botão *"Usar os valores das faturas importadas"* joga o realizado
para dentro do previsto de uma vez.

Duas escolhas que valem explicar:

- **O mês de um gasto de cartão é o da FATURA, não o da compra.** Uma compra de
  28/08 que cai na fatura de setembro pertence a setembro — é quando o dinheiro
  sai da conta, e é assim que a planilha sempre tratou.
- **Cartão sem lançamento no mês aparece como "—", não como R$ 0.** "Fatura
  ainda não importada" e "não gastei nada" são coisas diferentes; mostrar zero
  exibiria uma economia que não aconteceu. Pelo mesmo motivo, linhas como
  *Energia Elétrica* não têm realizado: não existe vínculo 1-para-1 entre a
  linha e um gasto do banco, e um número que parece medido sem ser é pior que
  nenhum número.

Importe sua planilha de uma vez (idempotente — rodar de novo sobrescreve o
mesmo ano):

```bash
pip install openpyxl
python scripts/importar_planilha.py Contas_pessoais.xlsx --simular   # confere
python scripts/importar_planilha.py Contas_pessoais.xlsx             # grava
```

Ele lê a estrutura pelo conteúdo (acha o cabeçalho Jan..Dez e segue os
marcadores de seção), não por número de linha fixo, então continua funcionando
se você acrescentar linhas à planilha.

### Juros em destaque

Pix parcelado e parcelamento de fatura vêm com juros embutidos. O parser
identifica os dois formatos que o Itaú usa (`Principal (R$ X) + Juros (R$ Y)` na
mesma linha, ou em duas linhas seguidas — que são **fundidas em um lançamento só**,
senão o mês contaria o mesmo dinheiro duas vezes) e acumula o total pago em
juros no mês e no ano.

---

## Rodando no Mac (caminho rápido)

```bash
git clone https://github.com/leandroregio-source/Contas-pessoais
cd Contas-pessoais
./iniciar.command
```

Ou simplesmente **clique duas vezes em `iniciar.command`** no Finder.

Na primeira vez ele cria o ambiente, instala tudo, pergunta um PIN e — se
houver um `.xlsx` na pasta — importa seu orçamento sozinho. Depois abre o
navegador. Da segunda vez em diante sobe em dois segundos, sem perguntar nada.

Para parar: `Ctrl+C` na janela. Para usar no celular, o script imprime o
endereço da rede local (mesmo Wi-Fi).

Roda com o Python que já vem no macOS (3.9+). Se faltar:
`brew install python`.

**Onde ficam os dados:** num arquivo `financas.sqlite3` dentro da pasta, só no
seu Mac. Nada sai daí. O `.gitignore` já protege esse arquivo, o `.env` e
qualquer `.xlsx`/`.pdf` que você deixar na pasta — nenhum deles vai para o
GitHub.

Guarde uma cópia desse arquivo de vez em quando; é todo o seu histórico.

### Se preferir na mão

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt openpyxl
cp .env.example .env          # preencha SECRET_KEY e APP_PIN
python run.py                 # http://localhost:5000
```

Com `SUPABASE_URL` vazio o app usa SQLite local automaticamente — é o modo
padrão e não exige nada além do que está acima.

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

### Supabase (opcional, só se quiser sincronizar entre aparelhos)

Não é necessário para usar o app. O SQLite local dá conta de tudo; o Supabase
serve para o dia em que você quiser os mesmos dados no Mac e no celular sem
depender de um estar ligado.

1. Crie um projeto pessoal novo (o plano gratuito basta).
2. Rode `supabase/schema.sql` inteiro no **SQL Editor**.
3. Copie a URL e a chave `service_role` (Settings → API) para o `.env`.

Se você já tinha rodado o `schema.sql` antes do orçamento existir, rode também
`supabase/migration_002_orcamento.sql`. Em banco novo, o `schema.sql` sozinho
já cria tudo — não rode os dois.

O schema cria `gastos`, `faturas`, `parcelas_futuras`, `orcamento_linhas`,
`orcamento_valores` e `orcamento_config` com índices e
**RLS ligada sem nenhuma policy** — mais os `GRANT`s revogados de `anon` e
`authenticated`. Traduzindo: mesmo que a chave pública vaze, ela lê zero linha.
Quem opera o banco é só o servidor, com a `service_role`. Quem autentica a
pessoa é o PIN do Flask.

### Instalar no celular

Com o Mac ligado e na mesma rede Wi-Fi, abra no celular o endereço que o
`iniciar.command` imprime (algo como `http://192.168.0.10:5000`) →
**Adicionar à tela de início**. Vira app com ícone próprio e tela cheia.

Uma limitação a saber: por HTTP em rede local a **câmera não abre** (navegador
só libera em contexto seguro), então a tela de foto não funciona assim — o
resto funciona. Para ter a câmera e usar fora de casa é preciso HTTPS, via
túnel (Cloudflare Tunnel, Tailscale) ou qualquer PaaS:

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
    orcamento.py         orçamento mensal           ← regra pura, testada
    normalize.py         validação de entrada       ← regra pura, testada
    pdf_text.py          PDF → texto (pdfplumber)
    claude_extract.py    visão (recibo) + categoria em lote
iniciar.command          sobe tudo no Mac com um clique
scripts/
  importar_planilha.py   carrega a planilha .xlsx para dentro do orçamento
static/
  js/{app,api,screens,charts,orcamento}.js   ES modules, sem framework
  css/app.css            tokens de cor, claro e escuro
  sw.js                  service worker
supabase/
  schema.sql                    banco novo: roda só este
  migration_002_orcamento.sql   banco que já existia antes do orçamento
tests/                   72 testes, sem rede
```

**Toda regra de negócio vive em `app/services/*` como função pura** — recebe
dados, devolve dados, não toca em rede nem banco. É o que permite os 72 testes
rodarem em menos de 1 s e o que mantém a lógica verificável. Os testes do
orçamento conferem os resultados contra os números da planilha real, célula a
célula (saldo final de dezembro, total de saídas do ano, encadeamento mês a mês).

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
