-- ===========================================================================
-- Migração 002 — Orçamento mensal
--
-- Só para quem JÁ rodou o schema.sql antes do orçamento existir.
-- Em banco novo, schema.sql sozinho já cria tudo isto — não rode os dois.
-- Seguro rodar mais de uma vez.
-- ===========================================================================

alter table public.gastos add column if not exists cartao text;

create index if not exists idx_gastos_cartao on public.gastos (cartao, fatura_referencia)
    where cartao is not null;

create table if not exists public.orcamento_linhas (
    id    uuid primary key default gen_random_uuid(),
    secao text not null check (secao in ('receita','fixa','cartao')),
    nome  text not null check (length(nome) between 1 and 80),
    chave text not null unique,
    ordem smallint not null default 0,
    ativo boolean not null default true
);

create index if not exists idx_orc_linhas_secao on public.orcamento_linhas (secao, ordem);

create table if not exists public.orcamento_valores (
    linha_id uuid not null references public.orcamento_linhas(id) on delete cascade,
    mes      text not null check (mes ~ '^\d{4}-(0[1-9]|1[0-2])$'),
    previsto numeric(14,2) not null default 0,
    primary key (linha_id, mes)
);

create index if not exists idx_orc_valores_mes on public.orcamento_valores (mes);

create table if not exists public.orcamento_config (
    chave text primary key,
    valor text
);

grant all on public.orcamento_linhas  to service_role;
grant all on public.orcamento_valores to service_role;
grant all on public.orcamento_config  to service_role;

revoke all on public.orcamento_linhas  from anon, authenticated;
revoke all on public.orcamento_valores from anon, authenticated;
revoke all on public.orcamento_config  from anon, authenticated;

alter table public.orcamento_linhas  enable row level security;
alter table public.orcamento_valores enable row level security;
alter table public.orcamento_config  enable row level security;

alter table public.orcamento_linhas  force row level security;
alter table public.orcamento_valores force row level security;
alter table public.orcamento_config  force row level security;
