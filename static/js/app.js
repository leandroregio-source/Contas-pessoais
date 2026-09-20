/* Roteador por hash + estado global mínimo. */
import { api, limparCache, mesPorExtenso, mesVizinho } from "./api.js";
import { dashboard, foto, importar, historico, insights } from "./screens.js";

const TELAS = {
  "": { titulo: "Resumo", montar: dashboard, seletorMes: true },
  "foto": { titulo: "Novo gasto", montar: foto, seletorMes: false },
  "importar": { titulo: "Importar fatura", montar: importar, seletorMes: false },
  "historico": { titulo: "Histórico", montar: historico, seletorMes: false },
  "insights": { titulo: "Insights", montar: insights, seletorMes: true },
};

const estado = { mes: "", meta: null };

const $ = (s) => document.querySelector(s);
const rotaAtual = () => (location.hash.replace(/^#\/?/, "").split("?")[0] || "");

function marcarNav(rota) {
  document.querySelectorAll(".nav a").forEach((a) => {
    const alvo = a.getAttribute("href").replace(/^#\/?/, "");
    if (alvo === rota) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
}

function pintarSeletorMes(mostrar) {
  const barra = $("#sel-mes");
  barra.hidden = !mostrar;
  if (mostrar) $("#rot-mes").textContent = mesPorExtenso(estado.mes);
}

let tokenRender = 0;

async function render() {
  const rota = rotaAtual();
  const tela = TELAS[rota] || TELAS[""];
  const meu = ++tokenRender;

  $("#titulo").textContent = tela.titulo;
  marcarNav(rota in TELAS ? rota : "");
  pintarSeletorMes(tela.seletorMes);

  const alvo = $("#conteudo");
  alvo.innerHTML = "";
  await tela.montar(estado, alvo);

  // Navegação rápida pode terminar fora de ordem; só a última pinta a tela.
  if (meu !== tokenRender) return;
  window.scrollTo({ top: 0 });
}

function trocarMes(passo) {
  estado.mes = mesVizinho(estado.mes, passo);
  try { sessionStorage.setItem("mes", estado.mes); } catch { /* modo privado */ }
  render();
}

async function iniciar() {
  try {
    estado.meta = await api.get("/api/meta");
  } catch {
    $("#conteudo").innerHTML =
      `<div class="erro">Não consegui falar com o servidor. Verifique a conexão.</div>`;
    return;
  }

  let salvo = null;
  try { salvo = sessionStorage.getItem("mes"); } catch { /* modo privado */ }
  estado.mes = salvo || estado.meta.mes_atual;

  $("#mes-ant").addEventListener("click", () => trocarMes(-1));
  $("#mes-prox").addEventListener("click", () => trocarMes(1));
  $("#atualizar").addEventListener("click", () => { limparCache(); render(); });

  window.addEventListener("hashchange", render);
  // Redesenha os canvas ao girar o aparelho — a largura muda.
  let redim;
  window.addEventListener("resize", () => {
    clearTimeout(redim);
    redim = setTimeout(render, 220);
  });

  await render();

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => { /* http simples */ });
  }
}

iniciar();
