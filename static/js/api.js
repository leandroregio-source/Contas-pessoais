/* Cliente HTTP + formatação. Nada de lógica de tela aqui. */

export const brl = (n) =>
  (Number(n) || 0).toLocaleString("pt-BR", {
    style: "currency", currency: "BRL", minimumFractionDigits: 2,
  });

export const brlCurto = (n) => {
  const v = Math.abs(Number(n) || 0);
  if (v >= 1000) return `R$ ${(v / 1000).toFixed(v >= 10000 ? 0 : 1)}k`;
  return `R$ ${v.toFixed(0)}`;
};

const MESES = ["jan", "fev", "mar", "abr", "mai", "jun",
               "jul", "ago", "set", "out", "nov", "dez"];

export const rotuloMes = (ym) => {
  if (!ym || ym.length < 7) return ym || "";
  return `${MESES[Number(ym.slice(5, 7)) - 1]}/${ym.slice(2, 4)}`;
};

export const mesPorExtenso = (ym) => {
  const nomes = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
                 "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
  if (!ym || ym.length < 7) return ym || "";
  return `${nomes[Number(ym.slice(5, 7)) - 1]} de ${ym.slice(0, 4)}`;
};

export const dataBR = (iso) => {
  if (!iso) return "";
  const [a, m, d] = String(iso).slice(0, 10).split("-");
  return `${d}/${m}`;
};

export const mesDe = (iso) => String(iso || "").slice(0, 7);

export function mesVizinho(ym, passo) {
  let ano = Number(ym.slice(0, 4));
  let mes = Number(ym.slice(5, 7)) + passo;
  while (mes < 1) { mes += 12; ano -= 1; }
  while (mes > 12) { mes -= 12; ano += 1; }
  return `${String(ano).padStart(4, "0")}-${String(mes).padStart(2, "0")}`;
}

export class ErroApi extends Error {
  constructor(mensagem, status) {
    super(mensagem);
    this.status = status;
  }
}

async function tratar(resposta) {
  if (resposta.status === 401) {
    location.href = "/login";
    throw new ErroApi("Sessão expirada", 401);
  }
  const tipo = resposta.headers.get("content-type") || "";
  const corpo = tipo.includes("json") ? await resposta.json() : await resposta.text();
  if (!resposta.ok) {
    const msg = (corpo && corpo.erro) || `Falha na requisição (${resposta.status})`;
    throw new ErroApi(msg, resposta.status);
  }
  return corpo;
}

export const api = {
  async get(caminho) {
    return tratar(await fetch(caminho, { headers: { Accept: "application/json" } }));
  },
  async post(caminho, dados) {
    return tratar(await fetch(caminho, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dados),
    }));
  },
  async patch(caminho, dados) {
    return tratar(await fetch(caminho, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dados),
    }));
  },
  async del(caminho) {
    return tratar(await fetch(caminho, { method: "DELETE" }));
  },
  async enviarArquivo(caminho, formData) {
    return tratar(await fetch(caminho, { method: "POST", body: formData }));
  },
};

/* Cache em memória por rota. O dashboard e os insights leem a mesma janela
   de meses; sem isto, trocar de aba refaz a consulta inteira à toa. */
const cache = new Map();
const TTL = 60_000;

export async function getCache(caminho) {
  const salvo = cache.get(caminho);
  if (salvo && Date.now() - salvo.em < TTL) return salvo.dados;
  const dados = await api.get(caminho);
  cache.set(caminho, { dados, em: Date.now() });
  return dados;
}

export function limparCache() {
  cache.clear();
}
