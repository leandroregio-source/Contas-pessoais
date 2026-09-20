/* Renderização das cinco telas. Cada uma exporta montar(estado). */
import {
  api, getCache, limparCache, brl, brlCurto, rotuloMes, mesPorExtenso,
  dataBR, mesDe, mesVizinho,
} from "./api.js";
import { barrasCategoria, barrasMensais, ligarDica } from "./charts.js";

const $ = (sel, raiz = document) => raiz.querySelector(sel);
const $$ = (sel, raiz = document) => [...raiz.querySelectorAll(sel)];

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const carregando = (msg = "Carregando") =>
  `<div class="carregando"><span class="spin"></span> ${esc(msg)}…</div>`;

const erroHtml = (msg) => `<div class="erro">${esc(msg)}</div>`;

/* Variação sempre com SETA + número. A cor reforça, nunca carrega sozinha
   a informação — quem não distingue verde de vermelho lê a seta e o sinal. */
function deltaHtml(delta, pct) {
  if (delta === 0 || delta == null) {
    return `<span class="delta neutro">— estável</span>`;
  }
  const sobe = delta > 0;
  const seta = sobe ? "▲" : "▼";
  const pctTxt = pct == null ? "" : ` (${sobe ? "+" : ""}${pct}%)`;
  return `<span class="delta ${sobe ? "sobe" : "desce"}">${seta} ${
    sobe ? "+" : "−"}${brl(Math.abs(delta)).replace("R$", "R$")}${pctTxt}</span>`;
}

function optCategorias(cats, atual) {
  return cats.map((c) =>
    `<option value="${c.valor}"${c.valor === atual ? " selected" : ""}>${esc(c.rotulo)}</option>`
  ).join("");
}

/* ======================================================== 1. DASHBOARD === */

export async function dashboard(estado, alvo) {
  alvo.innerHTML = carregando();
  let d;
  try {
    d = await getCache(`/api/dashboard?mes=${estado.mes}`);
  } catch (e) {
    alvo.innerHTML = erroHtml(e.message);
    return;
  }

  const semDados = d.quantidade === 0;
  alvo.innerHTML = `
    <div class="card">
      <h2>Total em <span class="sub">${esc(mesPorExtenso(d.mes))}</span></h2>
      <div class="heroi">
        <span class="valor">${brl(d.total)}</span>
        ${deltaHtml(d.delta, d.delta_pct)}
      </div>
      <div class="linha-meta">
        <span>${d.quantidade} lançamento${d.quantidade === 1 ? "" : "s"}</span>
        <span>Ticket médio <b>${brl(d.ticket_medio)}</b></span>
        ${d.juros > 0 ? `<span>Juros <b style="color:var(--ruim)">${brl(d.juros)}</b></span>` : ""}
      </div>
    </div>

    <div class="card">
      <h2>Evolução <span class="sub">últimos 6 meses</span></h2>
      <div class="gfx-wrap"><canvas class="gfx" id="gfx-meses"></canvas></div>
    </div>

    <div class="card">
      <h2>Por categoria</h2>
      ${semDados
        ? `<p class="vazio">Nenhum gasto em ${esc(mesPorExtenso(d.mes))}.<br>
             Importe a fatura ou registre um gasto por foto.</p>`
        : `<div class="gfx-wrap"><canvas class="gfx" id="gfx-cat"></canvas></div>
           <details style="margin-top:12px">
             <summary style="font-size:13px;color:var(--ink-muted);cursor:pointer">
               Ver como tabela
             </summary>
             <div class="tabela-rolagem"><table>
               <thead><tr><th>Categoria</th><th class="num">Mês</th>
                 <th class="num">Anterior</th><th class="num">Variação</th></tr></thead>
               <tbody>${(d.comparativo || []).map((l) => `
                 <tr><td>${esc(l.rotulo)}</td>
                     <td class="num">${brl(l.atual)}</td>
                     <td class="num">${brl(l.anterior)}</td>
                     <td class="num">${l.delta === 0 ? "—"
                        : `${l.delta > 0 ? "▲ +" : "▼ −"}${brl(Math.abs(l.delta))}`}</td>
                 </tr>`).join("")}</tbody>
             </table></div>
           </details>`}
    </div>

    ${d.maiores?.length ? `
    <div class="card">
      <h2>Maiores gastos do mês</h2>
      <ul class="lista">${d.maiores.map((g) => `
        <li>
          <div class="nome">
            <b>${esc(g.estabelecimento)}</b>
            <small>${dataBR(g.data)} · ${esc(g.categoria)}
              ${g.tem_juros ? '<span class="tag juros">juros</span>' : ""}</small>
          </div>
          <span class="cifra">${brl(g.valor)}</span>
        </li>`).join("")}
      </ul>
    </div>` : ""}
  `;

  const serie = (d.serie || []).map((p) => ({ ...p, rotulo: rotuloMes(p.mes) }));
  const cv = $("#gfx-meses", alvo);
  if (cv) {
    const achar = barrasMensais(cv, serie, { destaque: d.mes, formatar: brlCurto });
    ligarDica(cv, achar, (i) => `${rotuloMes(i.mes)} · ${brl(i.total)}`);
  }
  const cc = $("#gfx-cat", alvo);
  if (cc) {
    const achar = barrasCategoria(cc, d.categorias || [], { formatar: brlCurto });
    ligarDica(cc, achar, (i) => `${i.rotulo} · ${brl(i.total)} (${i.pct}%)`);
  }
}

/* ============================================================ 2. FOTO === */

export function foto(estado, alvo) {
  alvo.innerHTML = `
    <div class="card">
      <h2>Novo gasto por foto</h2>
      ${estado.meta.ia_disponivel ? "" :
        `<div class="erro">Leitura por foto indisponível: falta a
         <code>ANTHROPIC_API_KEY</code> no servidor. Use o formulário manual abaixo.</div>`}
      <label for="arq">Foto da nota, cupom ou comprovante</label>
      <input type="file" id="arq" accept="image/*" capture="environment"
             ${estado.meta.ia_disponivel ? "" : "disabled"}>
      <div id="area-preview"></div>
      <div id="area-msg"></div>
      <button class="btn" id="ler" ${estado.meta.ia_disponivel ? "" : "disabled"} disabled>
        Ler comprovante
      </button>
    </div>
    <div id="area-form"></div>
  `;

  const arq = $("#arq", alvo);
  const btn = $("#ler", alvo);
  const preview = $("#area-preview", alvo);
  const msg = $("#area-msg", alvo);

  arq.addEventListener("change", () => {
    msg.innerHTML = "";
    preview.innerHTML = "";
    const f = arq.files?.[0];
    btn.disabled = !f;
    if (!f) return;
    const url = URL.createObjectURL(f);
    preview.innerHTML = `<img class="preview-foto" src="${url}" alt="Prévia do comprovante">`;
    // Revoga só depois de carregar, senão a prévia pisca em branco no iOS.
    $("img", preview).onload = () => URL.revokeObjectURL(url);
  });

  btn.addEventListener("click", async () => {
    const f = arq.files?.[0];
    if (!f) return;
    btn.disabled = true;
    msg.innerHTML = carregando("Lendo o comprovante");
    const fd = new FormData();
    fd.append("foto", f);
    try {
      const d = await api.enviarArquivo("/api/recibo/extrair", fd);
      msg.innerHTML = d.confianca === "baixa"
        ? `<div class="erro">Leitura com confiança baixa — confira valor e data
           com atenção antes de salvar.</div>`
        : `<div class="ok">Comprovante lido. Confira e salve.</div>`;
      formularioGasto(estado, $("#area-form", alvo), {
        estabelecimento: d.estabelecimento,
        valor: d.valor,
        data: d.data || new Date().toISOString().slice(0, 10),
        categoria: d.categoria_sugerida,
        origem: d.origem_sugerida,
        observacoes: [d.observacao, (d.itens || [])
          .map((i) => `${i.descricao}: ${brl(i.valor)}`).join(" | ")]
          .filter(Boolean).join(" — "),
      }, "foto_recibo");
    } catch (e) {
      msg.innerHTML = erroHtml(e.message);
    } finally {
      btn.disabled = false;
    }
  });

  formularioGasto(estado, $("#area-form", alvo), null, "manual");
}

/* Formulário de confirmação/lançamento manual — usado pela tela de foto. */
function formularioGasto(estado, alvo, pre, criadoVia) {
  const hoje = new Date().toISOString().slice(0, 10);
  const v = pre || {};
  alvo.innerHTML = `
    <div class="card">
      <h2>${pre ? "Confira e salve" : "Lançar manualmente"}</h2>
      <form id="f-gasto" novalidate>
        <label for="g-estab">Estabelecimento</label>
        <input type="text" id="g-estab" required value="${esc(v.estabelecimento || "")}">
        <div class="grid2">
          <div>
            <label for="g-valor">Valor (R$)</label>
            <input type="text" inputmode="decimal" id="g-valor" required
                   value="${v.valor ? String(v.valor).replace(".", ",") : ""}">
          </div>
          <div>
            <label for="g-data">Data</label>
            <input type="date" id="g-data" required value="${esc(v.data || hoje)}">
          </div>
        </div>
        <div class="grid2">
          <div>
            <label for="g-cat">Categoria</label>
            <select id="g-cat">${optCategorias(estado.meta.categorias, v.categoria || "outros")}</select>
          </div>
          <div>
            <label for="g-origem">Origem</label>
            <select id="g-origem">
              ${["pix", "dinheiro", "debito", "cartao"].map((o) =>
                `<option value="${o}"${o === (v.origem || "pix") ? " selected" : ""}>${o}</option>`
              ).join("")}
            </select>
          </div>
        </div>
        <label for="g-obs">Observações</label>
        <textarea id="g-obs">${esc(v.observacoes || "")}</textarea>
        <div id="g-msg"></div>
        <button class="btn" type="submit" style="margin-top:14px">Salvar gasto</button>
      </form>
    </div>`;

  $("#f-gasto", alvo).addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const botao = $("button[type=submit]", alvo);
    const msg = $("#g-msg", alvo);
    botao.disabled = true;
    try {
      await api.post("/api/gastos", {
        estabelecimento: $("#g-estab", alvo).value,
        valor: $("#g-valor", alvo).value,
        data: $("#g-data", alvo).value,
        categoria: $("#g-cat", alvo).value,
        origem: $("#g-origem", alvo).value,
        observacoes: $("#g-obs", alvo).value,
        criado_via: criadoVia,
      });
      limparCache();
      msg.innerHTML = `<div class="ok">Gasto salvo.</div>`;
      $("#f-gasto", alvo).reset();
      $("#g-data", alvo).value = hoje;
    } catch (e) {
      msg.innerHTML = erroHtml(e.message);
    } finally {
      botao.disabled = false;
    }
  });
}

/* ======================================================== 3. IMPORTAR === */

export function importar(estado, alvo) {
  alvo.innerHTML = `
    <div class="card">
      <h2>Importar fatura do Itaú</h2>
      <p style="font-size:13.5px;color:var(--ink-2);margin:0 0 4px">
        Baixe a fatura em <b>PDF</b> pelo app do Itaú. A categoria já vem impressa
        em cada lançamento e é ela que usamos — a IA só entra no que sobrar.
      </p>
      <label for="pdf">Arquivo PDF</label>
      <input type="file" id="pdf" accept="application/pdf">
      <div class="grid2">
        <div>
          <label for="ref">Mês de referência</label>
          <input type="month" id="ref" value="${esc(estado.mes)}">
        </div>
        <div>
          <label for="cartao">Cartão</label>
          <select id="cartao">
            <option value="">— não informar —</option>
            ${(estado.meta.cartoes || []).map((c) =>
              `<option value="${esc(c.chave)}">${esc(c.nome)}</option>`).join("")}
          </select>
        </div>
      </div>
      <label for="senha">Senha do PDF (se houver)</label>
      <input type="password" id="senha" autocomplete="off">
      ${(estado.meta.cartoes || []).length ? `
        <p style="font-size:12.5px;color:var(--ink-muted);margin:6px 0 0">
          Informar o cartão liga esta fatura à linha correspondente do
          orçamento — o previsto passa a ser comparado com o valor real.
        </p>` : ""}
      <label style="display:flex;align-items:center;gap:8px;margin-top:12px">
        <input type="checkbox" id="usar-ia" checked style="width:auto"
               ${estado.meta.ia_disponivel ? "" : "disabled"}>
        <span style="font-weight:400">Sugerir categoria por IA no que a fatura não classificou</span>
      </label>
      <div id="imp-msg"></div>
      <button class="btn" id="analisar" disabled style="margin-top:14px">Analisar fatura</button>
    </div>
    <div id="imp-revisao"></div>`;

  const pdf = $("#pdf", alvo);
  const btn = $("#analisar", alvo);
  const msg = $("#imp-msg", alvo);

  pdf.addEventListener("change", () => { btn.disabled = !pdf.files?.[0]; });

  btn.addEventListener("click", async () => {
    btn.disabled = true;
    msg.innerHTML = carregando("Lendo a fatura");
    const fd = new FormData();
    fd.append("pdf", pdf.files[0]);
    fd.append("referencia", $("#ref", alvo).value);
    fd.append("senha", $("#senha", alvo).value);
    fd.append("usar_ia", $("#usar-ia", alvo).checked ? "1" : "0");
    try {
      const d = await api.enviarArquivo("/api/fatura/analisar", fd);
      d.cartao = $("#cartao", alvo).value || null;
      d.cartao_nome = $("#cartao", alvo).selectedOptions[0]?.text || "";
      msg.innerHTML = d.aviso_ia ? `<div class="erro">${esc(d.aviso_ia)}</div>` : "";
      revisaoFatura(estado, $("#imp-revisao", alvo), d);
      $("#imp-revisao", alvo).scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
      msg.innerHTML = erroHtml(e.message);
    } finally {
      btn.disabled = false;
    }
  });
}

/* Prévia editável — nada é salvo antes desta conferência. */
function revisaoFatura(estado, alvo, d) {
  const r = d.resumo;
  const divergencia = r.total != null
    ? Math.abs(r.total - r.total_extraido)
    : null;

  alvo.innerHTML = `
    <div class="card">
      <h2>Prévia · ${esc(r.referencia)}${
        d.cartao ? ` · <span class="sub">${esc(d.cartao_nome)}</span>` : ""}</h2>
      <div class="linha-meta" style="margin-top:0">
        <span>Extraído <b>${brl(r.total_extraido)}</b></span>
        ${r.total != null ? `<span>Fatura diz <b>${brl(r.total)}</b></span>` : ""}
        <span>${r.quantidade} lançamentos</span>
        ${r.total_juros > 0
          ? `<span>Juros <b style="color:var(--ruim)">${brl(r.total_juros)}</b></span>` : ""}
      </div>
      ${divergencia != null && divergencia > 1 ? `
        <div class="erro" style="margin-top:12px">
          Diferença de ${brl(divergencia)} entre o total impresso e a soma dos
          lançamentos lidos. Revise a lista antes de salvar.
        </div>` : ""}
      ${r.categorias_por_ia > 0 ? `
        <p style="font-size:13px;color:var(--ink-muted);margin:10px 0 0">
          ${r.categorias_por_ia} de ${r.sem_categoria_impressa} lançamentos sem
          categoria impressa foram sugeridos por IA
          <span class="tag ia">IA</span> — confira.
        </p>` : ""}
    </div>

    <div class="card">
      <h2>Lançamentos <span class="sub">edite a categoria se precisar</span></h2>
      <div id="itens">${d.lancamentos.map((l, i) => `
        <div class="revisao-item" data-i="${i}">
          <div class="revisao-head">
            <input type="checkbox" class="inc" checked style="width:auto" aria-label="Incluir">
            <div class="nome">${esc(l.estabelecimento)}
              ${l.categoria_incerta ? '<span class="tag ia">IA</span>' : ""}
              ${l.tem_juros ? '<span class="tag juros">juros</span>' : ""}
            </div>
            <span class="cifra">${brl(l.valor)}</span>
          </div>
          <div class="revisao-head" style="margin-top:6px">
            <small style="color:var(--ink-muted);width:44px">${dataBR(l.data)}</small>
            <select class="cat">${optCategorias(estado.meta.categorias, l.categoria)}</select>
            ${l.parcela_total ? `<small style="color:var(--ink-muted)">
              parc. ${l.parcela_atual}/${l.parcela_total}</small>` : ""}
          </div>
        </div>`).join("")}
      </div>
      <div id="conf-msg" style="margin-top:14px"></div>
      <button class="btn" id="confirmar" style="margin-top:6px">
        Salvar <span id="n-sel">${d.lancamentos.length}</span> lançamentos
      </button>
    </div>

    ${d.parcelas_futuras?.length ? `
    <div class="card">
      <h2>Já comprometido nas próximas faturas</h2>
      <ul class="lista">${d.parcelas_futuras.map((p) => `
        <li><div class="nome"><b>${esc(p.descricao)}</b>
          <small>${p.parcela_total ? `parcela ${p.parcela_atual}/${p.parcela_total}` : "—"}</small></div>
          <span class="cifra">${brl(p.valor_parcela)}</span></li>`).join("")}
      </ul>
    </div>` : ""}
  `;

  const itens = $$(".revisao-item", alvo);
  const contar = () => {
    $("#n-sel", alvo).textContent = itens.filter((el) => $(".inc", el).checked).length;
  };
  itens.forEach((el) => $(".inc", el).addEventListener("change", contar));

  $("#confirmar", alvo).addEventListener("click", async () => {
    const botao = $("#confirmar", alvo);
    const msg = $("#conf-msg", alvo);
    const escolhidos = itens
      .filter((el) => $(".inc", el).checked)
      .map((el) => {
        const l = { ...d.lancamentos[Number(el.dataset.i)] };
        l.categoria = $(".cat", el).value;
        delete l.categoria_incerta;
        return l;
      });
    if (!escolhidos.length) {
      msg.innerHTML = erroHtml("Selecione ao menos um lançamento.");
      return;
    }
    botao.disabled = true;
    msg.innerHTML = carregando("Salvando");
    try {
      const res = await api.post("/api/fatura/confirmar", {
        referencia: d.resumo.referencia,
        cartao: d.cartao,
        lancamentos: escolhidos,
        resumo: d.resumo,
        parcelas_futuras: d.parcelas_futuras,
      });
      limparCache();
      msg.innerHTML = `<div class="ok">${res.inseridos} salvos${
        res.duplicados ? ` · ${res.duplicados} já existiam (ignorados)` : ""}.</div>`;
      botao.textContent = "Salvo";
    } catch (e) {
      msg.innerHTML = erroHtml(e.message);
      botao.disabled = false;
    }
  });
}

/* ======================================================= 4. HISTÓRICO === */

export function historico(estado, alvo) {
  alvo.innerHTML = `
    <div class="card">
      <h2>Filtros</h2>
      <div class="grid2">
        <div><label for="h-de">De</label><input type="date" id="h-de" value="${estado.mes}-01"></div>
        <div><label for="h-ate">Até</label><input type="date" id="h-ate"></div>
      </div>
      <div class="grid2">
        <div><label for="h-cat">Categoria</label>
          <select id="h-cat"><option value="">Todas</option>
            ${optCategorias(estado.meta.categorias, "")}</select></div>
        <div><label for="h-org">Origem</label>
          <select id="h-org"><option value="">Todas</option>
            ${estado.meta.origens.map((o) => `<option value="${o}">${o}</option>`).join("")}</select></div>
      </div>
      <label for="h-busca">Buscar estabelecimento</label>
      <input type="search" id="h-busca" placeholder="ex.: netflix">
    </div>
    <div id="h-lista">${carregando()}</div>`;

  const campos = ["#h-de", "#h-ate", "#h-cat", "#h-org", "#h-busca"].map((s) => $(s, alvo));
  let timer;
  const buscar = async () => {
    const lista = $("#h-lista", alvo);
    lista.innerHTML = carregando();
    const q = new URLSearchParams();
    const [de, ate, cat, org, busca] = campos.map((c) => c.value.trim());
    if (de) q.set("desde", de);
    if (ate) q.set("ate", ate);
    if (cat) q.set("categoria", cat);
    if (org) q.set("origem", org);
    if (busca) q.set("busca", busca);
    try {
      const d = await api.get(`/api/gastos?${q}`);
      lista.innerHTML = !d.quantidade
        ? `<div class="card"><p class="vazio">Nenhum gasto com esses filtros.</p></div>`
        : `<div class="card">
             <h2>${d.quantidade} lançamentos <span class="sub">· ${brl(d.total)}</span></h2>
             <ul class="lista">${d.gastos.map((g) => `
               <li data-id="${esc(g.id)}">
                 <div class="nome">
                   <b>${esc(g.estabelecimento)}</b>
                   <small>${dataBR(g.data)} · ${esc(g.categoria)} · ${esc(g.origem)}
                     ${g.tem_juros ? `<span class="tag juros">juros ${brl(g.valor_juros || 0)}</span>` : ""}
                     ${g.parcela_total ? `<span class="tag">${g.parcela_atual}/${g.parcela_total}</span>` : ""}
                   </small>
                 </div>
                 <span class="cifra">${brl(g.valor)}</span>
                 <button class="excluir" aria-label="Excluir ${esc(g.estabelecimento)}"
                   style="background:none;border:0;color:var(--ink-muted);font-size:19px;
                          cursor:pointer;padding:4px 2px;min-width:34px">×</button>
               </li>`).join("")}
             </ul>
           </div>`;
      $$(".excluir", lista).forEach((b) => b.addEventListener("click", async () => {
        const li = b.closest("li");
        if (!confirm("Excluir este lançamento?")) return;
        try {
          await api.del(`/api/gastos/${li.dataset.id}`);
          limparCache();
          li.remove();
        } catch (e) { alert(e.message); }
      }));
    } catch (e) {
      lista.innerHTML = erroHtml(e.message);
    }
  };

  campos.forEach((c) => c.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(buscar, c.type === "search" ? 320 : 60);
  }));
  buscar();
}

/* ========================================================= 5. INSIGHTS === */

const ICONE = { juros: "⚠", acima_da_media: "↗", recorrente: "🔁", tendencia: "📈" };

export async function insights(estado, alvo) {
  alvo.innerHTML = carregando("Analisando seus gastos");
  let d;
  try {
    d = await getCache(`/api/insights?mes=${estado.mes}`);
  } catch (e) {
    alvo.innerHTML = erroHtml(e.message);
    return;
  }

  const recorrentes = (d.recorrentes || []).filter((r) => r.qtd_meses >= 3);

  alvo.innerHTML = `
    <div class="card">
      <h2>Sugestões · ${esc(mesPorExtenso(d.mes))}</h2>
      ${d.sugestoes.length
        ? d.sugestoes.map((s) => `
            <div class="sugestao ${esc(s.severidade)}">
              <span class="icone" aria-hidden="true">${ICONE[s.tipo] || "•"}</span>
              <div><b>${esc(s.titulo)}</b><p>${esc(s.detalhe)}</p></div>
            </div>`).join("")
        : `<p class="vazio">Sem alertas neste mês. Com 2–3 meses de histórico
             as sugestões ficam mais úteis.</p>`}
    </div>

    <div class="card">
      <h2>Juros pagos <span class="sub">o gasto mais evitável</span></h2>
      <div class="heroi"><span class="valor" style="${d.juros.total > 0
        ? "color:var(--ruim)" : ""}">${brl(d.juros.total)}</span></div>
      <div class="linha-meta">
        <span>${d.juros.quantidade} lançamento${d.juros.quantidade === 1 ? "" : "s"}
          com juros embutido na janela analisada</span>
      </div>
      ${d.juros.lancamentos?.length ? `
        <ul class="lista" style="margin-top:8px">${d.juros.lancamentos.slice(0, 6).map((g) => `
          <li><div class="nome"><b>${esc(g.estabelecimento)}</b>
            <small>${dataBR(g.data)} · total ${brl(g.valor)}</small></div>
            <span class="cifra" style="color:var(--ruim)">${brl(g.valor_juros || 0)}</span></li>`
        ).join("")}</ul>` : ""}
    </div>

    <div class="card">
      <h2>Gasto mês a mês <span class="sub">12 meses</span></h2>
      <div class="gfx-wrap"><canvas class="gfx" id="gfx-ano"></canvas></div>
    </div>

    <div class="card">
      <h2>Recorrentes <span class="sub">assinaturas e cobranças fixas</span></h2>
      ${recorrentes.length ? `
        <ul class="lista">${recorrentes.map((r) => `
          <li><div class="nome"><b>${esc(r.estabelecimento)}</b>
            <small>${r.qtd_meses} meses${r.consecutivos ? " seguidos" : ""} ·
              ${esc(r.categoria)}${r.ativa_no_mes_corrente ? "" : " · parou"}</small></div>
            <span class="cifra">${brl(r.valor_mediano)}<br>
              <small style="color:var(--ink-muted);font-weight:400">
                ${brl(r.custo_anual_estimado)}/ano</small></span></li>`).join("")}
        </ul>` : `<p class="vazio">Nada recorrente identificado ainda —
          são necessários pelo menos 3 meses de histórico.</p>`}
    </div>

    ${d.ranking_crescimento?.length ? `
    <div class="card">
      <h2>Categorias que mais cresceram</h2>
      <div class="tabela-rolagem"><table>
        <thead><tr><th>Categoria</th><th class="num">Mês</th>
          <th class="num">Anterior</th><th class="num">Alta</th></tr></thead>
        <tbody>${d.ranking_crescimento.map((l) => `
          <tr><td>${esc(l.rotulo)}</td><td class="num">${brl(l.atual)}</td>
            <td class="num">${brl(l.anterior)}</td>
            <td class="num" style="color:var(--ruim)">▲ +${brl(l.delta)}</td></tr>`).join("")}
        </tbody></table></div>
    </div>` : ""}

    ${d.parcelas_futuras?.length ? `
    <div class="card">
      <h2>Comprometido nas próximas faturas</h2>
      <div class="heroi"><span class="valor">${brl(d.total_comprometido)}</span></div>
      <ul class="lista" style="margin-top:8px">${d.parcelas_futuras.slice(0, 8).map((p) => `
        <li><div class="nome"><b>${esc(p.descricao)}</b>
          <small>${p.parcela_total ? `parcela ${p.parcela_atual}/${p.parcela_total}` : "—"}</small></div>
          <span class="cifra">${brl(p.valor_parcela)}</span></li>`).join("")}</ul>
    </div>` : ""}
  `;

  const cv = $("#gfx-ano", alvo);
  if (cv) {
    const serie = (d.serie || []).map((p) => ({ ...p, rotulo: rotuloMes(p.mes) }));
    const achar = barrasMensais(cv, serie, { destaque: d.mes, formatar: brlCurto });
    ligarDica(cv, achar, (i) => `${rotuloMes(i.mes)} · ${brl(i.total)}`);
  }
}
