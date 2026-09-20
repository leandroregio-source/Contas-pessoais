-- ===========================================================================
-- App de finanças pessoais — schema Supabase
-- Projeto PESSOAL e ISOLADO. Não compartilha banco com nenhum outro sistema.
--
-- Rode este arquivo no SQL Editor do Supabase (uma vez).
--
-- Modelo de segurança
-- -------------------
-- É um app single-user: quem autentica é o PIN no Flask, e o servidor fala
-- com o Postgres usando a service_role key (que nunca sai do servidor e
-- passa por cima da RLS, por design do Supabase).
--
-- Por isso as tabelas ficam com RLS LIGADA e SEM policy nenhuma para anon e
-- authenticated: qualquer chave pública (anon key vazada, cliente curioso,
-- extensão de navegador) lê exatamente zero linha. Os GRANTs também são
-- revogados — RLS sem policy já nega, mas revogar o privilégio é a segunda
-- tranca, e dado financeiro merece as duas.
-- ===========================================================================

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- gastos
-- ---------------------------------------------------------------------------
create table if not exists public.gastos (
    id                uuid primary key default gen_random_uuid(),
    data              date        not null,
    estabelecimento   text        not null check (length(estabelecimento) between 1 and 120),
    valor             numeric(12,2) not null check (valor <> 0),
    categoria         text        not null default 'outros'
                      check (categoria in ('supermercado','restaurante','lazer','saude',
                                           'viagem','outros','servicos','vestuario',
                                           'educacao','government')),
    origem            text        not null default 'cartao'
                      check (origem in ('cartao','pix','dinheiro','debito')),
    fatura_referencia text,                       -- 'AAAA-MM' da fatura, se veio de import
    tem_juros         boolean     not null default false,
    valor_juros       numeric(12,2),
    criado_via        text        not null default 'manual'
                      check (criado_via in ('import_fatura','foto_recibo','manual')),
    observacoes       text,
    parcela_atual     smallint,
    parcela_total     smallint,
    moeda_origem      text,                       -- 'USD' em lançamento internacional
    valor_origem      numeric(12,2),              -- valor na moeda original
    -- Chave de idempotência: reimportar a mesma fatura não duplica lançamento.
    hash_dedupe       text unique,
    criado_em         timestamptz not null default now(),

    constraint juros_coerente check (
        (tem_juros = false and valor_juros is null)
        or (tem_juros = true)
    )
);

-- Índices pensados nas consultas reais do app:
-- o dashboard varre uma JANELA DE MESES, a lista filtra por categoria/origem,
-- e a tela de juros busca só o subconjunto com juros (índice parcial, pequeno).
create index if not exists idx_gastos_data       on public.gastos (data desc);
create index if not exists idx_gastos_categoria  on public.gastos (categoria, data desc);
create index if not exists idx_gastos_origem     on public.gastos (origem, data desc);
create index if not exists idx_gastos_juros      on public.gastos (data desc) where tem_juros;
create index if not exists idx_gastos_referencia on public.gastos (fatura_referencia);

-- ---------------------------------------------------------------------------
-- faturas — resumo de cada fatura importada
-- ---------------------------------------------------------------------------
create table if not exists public.faturas (
    referencia   text primary key,                -- 'AAAA-MM'
    total        numeric(12,2),
    vencimento   date,
    limite_total numeric(12,2),
    encargos     numeric(12,2),
    importada_em timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- parcelas_futuras — seção "Compras parceladas - próximas faturas"
-- Mostra quanto do orçamento dos próximos meses já está comprometido.
-- ---------------------------------------------------------------------------
create table if not exists public.parcelas_futuras (
    id             uuid primary key default gen_random_uuid(),
    referencia     text not null references public.faturas(referencia) on delete cascade,
    descricao      text not null,
    parcela_atual  smallint,
    parcela_total  smallint,
    valor_parcela  numeric(12,2) not null,
    valor_restante numeric(12,2)
);

create index if not exists idx_parcelas_referencia on public.parcelas_futuras (referencia);

-- ===========================================================================
-- Segurança
-- ===========================================================================

-- service_role (o servidor Flask) é o único que opera as tabelas.
grant all on public.gastos           to service_role;
grant all on public.faturas          to service_role;
grant all on public.parcelas_futuras to service_role;

-- Ninguém mais. Chave anon vazada não lê nada.
revoke all on public.gastos           from anon, authenticated;
revoke all on public.faturas          from anon, authenticated;
revoke all on public.parcelas_futuras from anon, authenticated;

-- RLS ligada e sem policy: negação total para quem não for service_role.
alter table public.gastos           enable row level security;
alter table public.faturas          enable row level security;
alter table public.parcelas_futuras enable row level security;

-- Força a RLS inclusive para o dono da tabela (postgres), caso alguém
-- se conecte direto com essa role.
alter table public.gastos           force row level security;
alter table public.faturas          force row level security;
alter table public.parcelas_futuras force row level security;

-- ===========================================================================
-- Conferência rápida (deve devolver rowsecurity = true e 0 policies)
-- ===========================================================================
-- select tablename, rowsecurity from pg_tables
--  where schemaname = 'public' and tablename in ('gastos','faturas','parcelas_futuras');
-- select tablename, policyname from pg_policies where schemaname = 'public';
