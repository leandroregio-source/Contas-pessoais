/* Tela de Orçamento — o mesmo modelo da planilha, mais o realizado.

   Duas visões: MÊS (padrão, onde se digita) e ANO (a grade de 12 colunas,
   só leitura). No celular a grade de 12 colunas não se edita; a coluna do
   mês, sim. */
import { api, getCache, limparCache, brl, rotuloMes, mesPorExtenso } from "./api.js";
import { esc } from "./screens.js";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const ROTULO = { receita: "Receitas", fixa: "Despesas Fixas", cartao: "Cartões de Crédito" };
const SINAL = { receita: "+", fixa: "−", cartao: "−" };

/* Input de dinheiro: aceita "1.234,56" e "1234.56". No celular quem digita
   usa vírgula, então não dá para exigir ponto. */
const paraNumero = (txt) => {
  const t = String(txt ?? "").trim().replace(/[R$\s]/g, "");
  if (!t) return 0;
  const n = parseFloat(t.includes(",") ? t.replace(/\./g, "").replace(",", ".") : t);
  return Number.isFinite(n) ? n : NaN;
};
const paraCampo = (n) =>
  !n ? "" : Number(n).toLocaleString("pt-BR", { minimumFractionDigits: 2,
                                                maximumFractionDigits: 2 });

function difHtml(linha) {
  if (linha.realizado == null) {
    return `<small class="dif-na" title="Fatura ainda não importada para este cartão">—</small>`;
  }
  const d = linha.diferenca;
  if (Math.abs(d) < 0.01) return `<small class="dif ok">✓ igual</small>`;
  const acima = d > 0;
  return `<small class="dif ${acima ? "acima" : "abaixo"}">${
    acima ? "▲" : "▼"} ${brl(Math.abs(d))}</small>`;
}

export async function orcamento(estado, alvo) {
  alvo.innerHTML = `<div class="carregando"><span class="spin"></span> Carregando orçamento…</div>`;

  const ano = Number(estado.mes.slice(0, 4));
  let d;
  try {
    d = await getCache(`/api/orcamento?ano=${ano}`);
  } catch (e) {
    alvo.innerHTML = `<div class="erro">${esc(e.message)}</div>`;
    return;
  }

  if (!d.linhas.length) {
    alvo.innerHTML = `
      <div class="card">
        <h2>Orçamento</h2>
        <p style="font-size:14px;color:var(--ink-2)">
          Nada configurado ainda. Posso criar as linhas padrão — receitas,
          despesas fixas e os cartões — e você ajusta os valores depois.
        </p>
        <button class="btn" id="criar-padrao">Criar linhas padrão</button>
      </div>`;
    $("#criar-padrao", alvo).addEventListener("click", async (ev) => {
      ev.target.disabled = true;
      await api.post("/api/orcamento/inicializar", {});
      limparCache();
      orcamento(estado, alvo);
    });
    return;
  }

  // O mês selecionado no topo do app manda; se for de outro ano, cai em janeiro.
  const idx = Math.max(0, d.meses.findIndex((m) => m.mes === estado.mes));
  const mes = d.meses[idx];

  alvo.innerHTML = `
    <div class="card">
      <h2>Saldo · <span class="sub">${esc(mesPorExtenso(mes.mes))}</span></h2>
      <div class="heroi">
        <span class="valor" id="saldo-final">${brl(mes.final)}</span>
        <span class="delta ${mes.resultado >= 0 ? "desce" : "sobe"}">
          ${mes.resultado >= 0 ? "▲" : "▼"} ${brl(Math.abs(mes.resultado))} no mês
        </span>
      </div>
      <div class="linha-meta">
        <span>Abertura <b id="saldo-abertura"
              data-valor="${mes.abertura}">${brl(mes.abertura)}</b></span>
        <span>Receitas <b id="tot-receita">${brl(mes.receitas)}</b></span>
        <span>Saídas <b id="tot-saidas">${brl(mes.saidas)}</b></span>
      </div>
      ${mes.realizado_total != null ? `
        <div class="linha-meta" style="border-top:1px solid var(--grid);
             margin-top:10px;padding-top:10px">
          <span>Já lançado no app neste mês
            <b>${brl(mes.realizado_total)}</b></span>
        </div>` : ""}
    </div>

    <div id="secoes"></div>

    <div class="card">
      <h2>Ações</h2>
      <div class="btn-linha" style="flex-wrap:wrap;gap:8px">
        <button class="btn sec" id="btn-copiar" style="flex:1 1 46%">Repetir nos próximos meses</button>
        <button class="btn sec" id="btn-nova" style="flex:1 1 46%">Nova linha</button>
        <button class="btn sec" id="btn-saldo" style="flex:1 1 46%">Saldo inicial</button>
        <button class="btn sec" id="btn-ano" style="flex:1 1 46%">Ver ano inteiro</button>
      </div>
      <div id="acao-msg" style="margin-top:12px"></div>
      <div id="acao-form"></div>
    </div>

    <div id="grade-ano"></div>`;

  montarSecoes($("#secoes", alvo), d, mes, estado, alvo);
  montarAcoes(alvo, d, mes, estado);
}

/* -------------------------------------------------------------- seções --- */

function montarSecoes(alvo, d, mes, estado, raiz) {
  const porSecao = {};
  mes.linhas.forEach((l) => (porSecao[l.secao] ??= []).push(l));

  alvo.innerHTML = ["receita", "fixa", "cartao"].map((secao) => {
    const linhas = porSecao[secao] || [];
    if (!linhas.length) return "";
    const total = linhas.reduce((s, l) => s + l.previsto, 0);
    const temRealizado = secao === "cartao";
    return `
      <div class="card" data-secao="${secao}">
        <h2>${ROTULO[secao]}
          ${temRealizado ? '<span class="sub">previsto × fatura importada</span>' : ""}
        </h2>
        <div class="orc-linhas">
          ${linhas.map((l) => `
            <div class="orc-linha" data-id="${esc(l.linha_id)}">
              <span class="orc-nome" title="${esc(l.nome)}">${esc(l.nome)}</span>
              <span class="orc-campo">
                <span class="orc-sinal">${SINAL[secao]}</span>
                <input type="text" inputmode="decimal" class="orc-input"
                       value="${paraCampo(l.previsto)}" placeholder="0,00"
                       aria-label="Previsto para ${esc(l.nome)}">
              </span>
              ${temRealizado ? `<span class="orc-dif">${difHtml(l)}</span>` : ""}
            </div>`).join("")}
        </div>
        <div class="orc-total">
          <span>Total</span>
          <b data-total="${secao}">${brl(total)}</b>
        </div>
        ${secao === "cartao" ? `
          <button class="btn sec" id="btn-realizado" style="margin-top:12px">
            Usar os valores das faturas importadas
          </button>` : ""}
      </div>`;
  }).join("");

  // Salva ao sair do campo (não a cada tecla): uma requisição por edição
  // concluída, não por caractere digitado.
  $$(".orc-input", alvo).forEach((inp) => {
    inp.addEventListener("focus", () => inp.select());
    inp.addEventListener("blur", () => salvarCampo(inp, mes.mes, estado, raiz));
    inp.addEventListener("keydown", (ev) => { if (ev.key === "Enter") inp.blur(); });
  });

  const btnReal = $("#btn-realizado", alvo);
  if (btnReal) {
    btnReal.addEventListener("click", async () => {
      btnReal.disabled = true;
      const msg = $("#acao-msg", raiz);
      try {
        const r = await api.post("/api/orcamento/usar-realizado", { mes: mes.mes });
        limparCache();
        msg.innerHTML = `<div class="ok">${r.gravados} cartão(ões) atualizados com o valor da fatura.</div>`;
        orcamento(estado, raiz);
      } catch (e) {
        msg.innerHTML = `<div class="erro">${esc(e.message)}</div>`;
        btnReal.disabled = false;
      }
    });
  }
}

async function salvarCampo(input, mesRef, estado, raiz) {
  const numero = paraNumero(input.value);
  if (Number.isNaN(numero)) {
    input.classList.add("invalido");
    return;
  }
  input.classList.remove("invalido");
  const original = input.dataset.salvo ?? input.defaultValue;
  if (paraCampo(numero) === original) return;

  input.classList.add("salvando");
  try {
    await api.put("/api/orcamento/valores", {
      valores: [{
        linha_id: input.closest(".orc-linha").dataset.id,
        mes: mesRef, previsto: numero,
      }],
    });
    input.value = paraCampo(numero);
    input.dataset.salvo = input.value;
    limparCache();
    recalcularNaTela(raiz, mesRef);
  } catch (e) {
    input.classList.add("invalido");
    $("#acao-msg", raiz).innerHTML = `<div class="erro">${esc(e.message)}</div>`;
  } finally {
    input.classList.remove("salvando");
  }
}

/* Recalcula os totais na tela sem ir ao servidor — o cálculo é o mesmo do
   backend e a resposta imediata é o que faz a digitação parecer planilha. */
function recalcularNaTela(raiz, mesRef) {
  const soma = (secao) => $$(`[data-secao="${secao}"] .orc-input`, raiz)
    .reduce((s, i) => s + (paraNumero(i.value) || 0), 0);

  const receitas = soma("receita");
  const fixas = soma("fixa");
  const cartoes = soma("cartao");
  const saidas = fixas + cartoes;
  const abertura = Number($("#saldo-abertura", raiz)?.dataset.valor || 0);

  const set = (sel, v) => { const el = $(sel, raiz); if (el) el.textContent = brl(v); };
  set('[data-total="receita"]', receitas);
  set('[data-total="fixa"]', fixas);
  set('[data-total="cartao"]', cartoes);
  set("#tot-receita", receitas);
  set("#tot-saidas", saidas);
  set("#saldo-final", abertura + receitas - saidas);

  // O encadeamento dos meses seguintes muda: marca a grade como desatualizada.
  const grade = $("#grade-ano", raiz);
  if (grade && grade.innerHTML.trim()) grade.dataset.stale = "1";
}

/* -------------------------------------------------------------- ações --- */

function montarAcoes(raiz, d, mes, estado) {
  const form = $("#acao-form", raiz);
  const msg = $("#acao-msg", raiz);
  const fechar = () => { form.innerHTML = ""; };

  $("#btn-copiar", raiz).addEventListener("click", () => {
    const restantes = d.meses.map((m) => m.mes).filter((m) => m > mes.mes);
    if (!restantes.length) {
      msg.innerHTML = `<div class="erro">${rotuloMes(mes.mes)} é o último mês do ano.</div>`;
      return;
    }
    form.innerHTML = `
      <label>Repetir os valores de <b>${esc(mesPorExtenso(mes.mes))}</b> em:</label>
      <div style="display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 4px">
        ${restantes.map((m) => `
          <label style="display:flex;align-items:center;gap:5px;font-weight:400;margin:0">
            <input type="checkbox" class="cp" value="${m}" checked style="width:auto">
            ${rotuloMes(m)}
          </label>`).join("")}
      </div>
      <div class="btn-linha">
        <button class="btn" id="cp-ok">Repetir</button>
        <button class="btn sec" id="cp-x">Cancelar</button>
      </div>`;
    $("#cp-x", form).addEventListener("click", fechar);
    $("#cp-ok", form).addEventListener("click", async () => {
      const para = $$(".cp:checked", form).map((c) => c.value);
      if (!para.length) return;
      $("#cp-ok", form).disabled = true;
      try {
        await api.post("/api/orcamento/copiar", { de: mes.mes, para });
        limparCache();
        msg.innerHTML = `<div class="ok">Valores repetidos em ${para.length} mês(es).</div>`;
        fechar();
      } catch (e) {
        msg.innerHTML = `<div class="erro">${esc(e.message)}</div>`;
        $("#cp-ok", form).disabled = false;
      }
    });
  });

  $("#btn-nova", raiz).addEventListener("click", () => {
    form.innerHTML = `
      <label for="nl-nome">Nome da linha</label>
      <input type="text" id="nl-nome" placeholder="ex.: Academia">
      <label for="nl-secao">Seção</label>
      <select id="nl-secao">
        <option value="fixa">Despesa Fixa</option>
        <option value="receita">Receita</option>
        <option value="cartao">Cartão de Crédito</option>
      </select>
      <div class="btn-linha">
        <button class="btn" id="nl-ok">Criar</button>
        <button class="btn sec" id="nl-x">Cancelar</button>
      </div>`;
    $("#nl-x", form).addEventListener("click", fechar);
    $("#nl-ok", form).addEventListener("click", async () => {
      const nome = $("#nl-nome", form).value.trim();
      if (!nome) return;
      $("#nl-ok", form).disabled = true;
      try {
        await api.post("/api/orcamento/linhas",
                       { nome, secao: $("#nl-secao", form).value });
        limparCache();
        fechar();
        orcamento(estado, raiz.closest("#conteudo") || raiz);
      } catch (e) {
        msg.innerHTML = `<div class="erro">${esc(e.message)}</div>`;
        $("#nl-ok", form).disabled = false;
      }
    });
  });

  $("#btn-saldo", raiz).addEventListener("click", () => {
    const si = d.saldo_inicial || {};
    form.innerHTML = `
      <p style="font-size:13px;color:var(--ink-2);margin:4px 0 0">
        O saldo digitado uma vez; daí em diante cada mês abre com o
        fechamento do anterior.
      </p>
      <label for="si-mes">A partir de</label>
      <input type="month" id="si-mes" value="${esc(si.mes || mes.mes)}">
      <label for="si-valor">Saldo nessa data (R$)</label>
      <input type="text" inputmode="decimal" id="si-valor" value="${paraCampo(si.valor || 0)}">
      <div class="btn-linha">
        <button class="btn" id="si-ok">Salvar</button>
        <button class="btn sec" id="si-x">Cancelar</button>
      </div>`;
    $("#si-x", form).addEventListener("click", fechar);
    $("#si-ok", form).addEventListener("click", async () => {
      $("#si-ok", form).disabled = true;
      try {
        await api.put("/api/orcamento/saldo-inicial", {
          mes: $("#si-mes", form).value,
          valor: paraNumero($("#si-valor", form).value),
        });
        limparCache();
        fechar();
        orcamento(estado, raiz.closest("#conteudo") || raiz);
      } catch (e) {
        msg.innerHTML = `<div class="erro">${esc(e.message)}</div>`;
        $("#si-ok", form).disabled = false;
      }
    });
  });

  $("#btn-ano", raiz).addEventListener("click", async () => {
    const grade = $("#grade-ano", raiz);
    if (grade.innerHTML.trim() && grade.dataset.stale !== "1") {
      grade.innerHTML = "";
      return;
    }
    grade.dataset.stale = "";
    grade.innerHTML = `<div class="carregando"><span class="spin"></span></div>`;
    try {
      const atual = await getCache(`/api/orcamento?ano=${d.ano}`);
      grade.innerHTML = gradeAnual(atual, mes.mes);
      grade.scrollIntoView({ behavior: "smooth", block: "start" });
      // Rola até o mês em foco: abrir em janeiro mostra meses vazios e
      // esconde justamente a coluna que interessa.
      const rolagem = grade.querySelector(".tabela-rolagem");
      const coluna = grade.querySelector(`[data-col="${mes.mes}"]`);
      if (rolagem && coluna) {
        rolagem.scrollLeft = Math.max(
          0, coluna.offsetLeft - rolagem.clientWidth / 2
        );
      }
    } catch (e) {
      grade.innerHTML = `<div class="erro">${esc(e.message)}</div>`;
    }
  });
}

/* ---------------------------------------------------------- grade anual --- */

function gradeAnual(d, mesFoco) {
  const meses = d.meses;
  const cab = meses.map((m) =>
    `<th class="num${m.mes === mesFoco ? " foco" : ""}" data-col="${m.mes}">${
      rotuloMes(m.mes)}</th>`).join("");
  const faixa = (rotulo) => `
    <tr class="secao">
      <td>${esc(rotulo)}</td>
      ${meses.map(() => "<td></td>").join("")}<td></td>
    </tr>`;

  const linhaTotais = (rotulo, pega, forte = false) => `
    <tr${forte ? ' class="forte"' : ""}>
      <td>${esc(rotulo)}</td>
      ${meses.map((m) => `<td class="num">${brl(pega(m))}</td>`).join("")}
      <td class="num">${forte ? "" : brl(meses.reduce((s, m) => s + pega(m), 0))}</td>
    </tr>`;

  const porSecao = (secao) => (d.linhas || [])
    .filter((l) => l.secao === secao && l.ativo !== false)
    .map((l) => `
      <tr>
        <td>${esc(l.nome)}</td>
        ${meses.map((m) => {
          const x = m.linhas.find((y) => y.linha_id === l.id);
          return `<td class="num">${x && x.previsto ? brl(x.previsto) : "—"}</td>`;
        }).join("")}
        <td class="num">${brl(d.total_por_linha[l.id] || 0)}</td>
      </tr>`).join("");

  return `
    <div class="card">
      <h2>${d.ano} <span class="sub">arraste para o lado</span></h2>
      <div class="tabela-rolagem">
        <table class="grade">
          <thead><tr><th>Linha</th>${cab}<th class="num">Total</th></tr></thead>
          <tbody>
            ${faixa("Saldo de Abertura")}
            ${linhaTotais("Abertura", (m) => m.abertura, true)}
            ${faixa("Receitas")}
            ${porSecao("receita")}
            ${linhaTotais("Total de Receitas", (m) => m.receitas)}
            ${faixa("Despesas Fixas")}
            ${porSecao("fixa")}
            ${linhaTotais("Total Despesas Fixas", (m) => m.fixas)}
            ${faixa("Cartões de Crédito")}
            ${porSecao("cartao")}
            ${linhaTotais("Total Cartões", (m) => m.cartoes)}
            ${faixa("Resumo")}
            ${linhaTotais("Total de Saídas", (m) => m.saidas)}
            ${linhaTotais("Resultado do Mês", (m) => m.resultado)}
            ${linhaTotais("Saldo Final", (m) => m.final, true)}
          </tbody>
        </table>
      </div>
    </div>`;
}
