/* Gráficos em canvas, sem biblioteca externa.
   Motivo: CSP restritiva (nada de CDN), funciona offline e o bundle fica em
   zero KB de dependência — num app que roda no celular isso é o que importa.

   Forma escolhida: BARRAS, não pizza. São até 10 categorias ordenadas por
   magnitude; barra horizontal lê direto no celular e a pizza não. Série única
   por gráfico, então uma cor só (a identidade vem do rótulo, não do matiz) e
   nenhuma legenda é necessária. */

const token = (nome) =>
  getComputedStyle(document.documentElement).getPropertyValue(nome).trim();

/* Canvas nítido em tela retina: o buffer segue o devicePixelRatio e o CSS
   mantém o tamanho lógico. */
function preparar(canvas, alturaCss) {
  const dpr = Math.min(window.devicePixelRatio || 1, 3);
  const largura = canvas.parentElement.clientWidth || 320;
  canvas.style.width = "100%";
  canvas.style.height = `${alturaCss}px`;
  canvas.width = Math.round(largura * dpr);
  canvas.height = Math.round(alturaCss * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, largura, alturaCss);
  return { ctx, largura, altura: alturaCss };
}

/* Retângulo com as PONTAS DE DADO arredondadas (4px) e a base encostada no
   eixo — a ponta quadrada no baseline é o que ancora a leitura. */
function barra(ctx, x, y, w, h, r, lado) {
  const raio = Math.max(0, Math.min(r, w / 2, h / 2));
  ctx.beginPath();
  if (lado === "horizontal") {
    ctx.moveTo(x, y);
    ctx.lineTo(x + w - raio, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + raio);
    ctx.lineTo(x + w, y + h - raio);
    ctx.quadraticCurveTo(x + w, y + h, x + w - raio, y + h);
    ctx.lineTo(x, y + h);
  } else {
    ctx.moveTo(x, y + h);
    ctx.lineTo(x, y + raio);
    ctx.quadraticCurveTo(x, y, x + raio, y);
    ctx.lineTo(x + w - raio, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + raio);
    ctx.lineTo(x + w, y + h);
  }
  ctx.closePath();
  ctx.fill();
}

/* Mantém um rótulo centralizado dentro do canvas: o último mês fica no fim
   da área útil e, centrado na barra, metade do texto sairia cortada. */
function centrar(ctx, texto, cx, largura) {
  const meia = ctx.measureText(texto).width / 2;
  return Math.max(meia, Math.min(cx, largura - meia));
}

function fonte(ctx, tamanho, peso = 400) {
  ctx.font = `${peso} ${tamanho}px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`;
}

/* ------------------------------------------------------------------------
   Barras horizontais: gasto por categoria no mês.
   ------------------------------------------------------------------------ */
export function barrasCategoria(canvas, itens, { formatar }) {
  const dados = itens.filter((d) => d.total > 0);
  const ALTURA_LINHA = 34;
  const alturaCss = Math.max(60, dados.length * ALTURA_LINHA + 8);
  const { ctx, largura } = preparar(canvas, alturaCss);
  if (!dados.length) return () => null;

  const max = Math.max(...dados.map((d) => d.total));
  const LABEL = Math.min(112, Math.max(78, largura * 0.3));
  const VALOR = 74;
  const trilho = Math.max(24, largura - LABEL - VALOR - 8);
  const cor = token("--serie");
  const zonas = [];

  dados.forEach((d, i) => {
    // 2px de superfície entre barras adjacentes: a folga é o separador.
    const y = i * ALTURA_LINHA + 4;
    const h = ALTURA_LINHA - 12;

    ctx.fillStyle = token("--ink-2");
    fonte(ctx, 13, 550);
    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    const nome = d.rotulo.length > 14 ? `${d.rotulo.slice(0, 13)}…` : d.rotulo;
    ctx.fillText(nome, 0, y + h / 2);

    const w = Math.max(3, (d.total / max) * trilho);
    ctx.fillStyle = cor;
    barra(ctx, LABEL, y, w, h, 4, "horizontal");

    // Rótulo direto em todas as barras: são poucas e o número é o ponto.
    ctx.fillStyle = token("--ink");
    fonte(ctx, 13, 600);
    ctx.textAlign = "right";
    ctx.fillText(formatar(d.total), largura, y + h / 2);

    zonas.push({ y0: y - 4, y1: y + h + 4, item: d });
  });

  return (mx, my) => zonas.find((z) => my >= z.y0 && my <= z.y1)?.item || null;
}

/* ------------------------------------------------------------------------
   Barras verticais: evolução do total mês a mês. O mês em foco fica na cor
   cheia; os demais em tom secundário — destaque por valor, não por legenda.
   ------------------------------------------------------------------------ */
export function barrasMensais(canvas, serie, { destaque, formatar }) {
  const ALTURA = 150;
  const { ctx, largura } = preparar(canvas, ALTURA);
  if (!serie.length) return () => null;

  const EIXO = 20;                    // faixa dos rótulos de mês
  const TOPO = 18;                    // respiro para o valor do mês em foco
  const area = ALTURA - EIXO - TOPO;
  const max = Math.max(...serie.map((d) => d.total), 1);
  const passo = largura / serie.length;
  const lg = Math.max(10, Math.min(38, passo - 10));   // >= 2px de folga
  const zonas = [];

  // Linha de base recessiva; sem grade — 6 barras não precisam de grade.
  ctx.strokeStyle = token("--baseline");
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, TOPO + area + 0.5);
  ctx.lineTo(largura, TOPO + area + 0.5);
  ctx.stroke();

  /* Com 12 meses em 390px os rótulos se encavalam. Mede o texto real e pula
     rótulos até caberem — o mês em foco é sempre rotulado. */
  fonte(ctx, 11, 500);
  const larguraRotulo = Math.max(...serie.map((d) => ctx.measureText(d.rotulo).width));
  const salto = Math.max(1, Math.ceil((larguraRotulo + 6) / passo));

  serie.forEach((d, i) => {
    const x = i * passo + (passo - lg) / 2;
    const h = Math.max(2, (d.total / max) * area);
    const y = TOPO + area - h;
    const foco = d.mes === destaque;

    ctx.fillStyle = foco ? token("--serie") : token("--serie-sec");
    barra(ctx, x, y, lg, h, 4, "vertical");

    // Conta o salto a partir do fim, para o último mês nunca cair fora.
    const rotular = foco || (serie.length - 1 - i) % salto === 0;
    if (rotular) {
      ctx.fillStyle = foco ? token("--ink") : token("--ink-muted");
      fonte(ctx, 11, foco ? 650 : 500);
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillText(d.rotulo, centrar(ctx, d.rotulo, x + lg / 2, largura), TOPO + area + 5);
    }

    // Rótulo direto só no mês em foco: número em toda barra vira ruído.
    if (foco && d.total > 0) {
      const txt = formatar(d.total);
      ctx.fillStyle = token("--ink");
      fonte(ctx, 11, 650);
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      ctx.fillText(txt, centrar(ctx, txt, x + lg / 2, largura), y - 3);
    }

    zonas.push({ x0: i * passo, x1: (i + 1) * passo, item: d });
  });

  return (mx) => zonas.find((z) => mx >= z.x0 && mx <= z.x1)?.item || null;
}

/* ------------------------------------------------------------------------
   Camada de hover/toque: um gráfico em tela é interativo por padrão.
   ------------------------------------------------------------------------ */
export function ligarDica(canvas, achar, texto) {
  const wrap = canvas.parentElement;
  let dica = wrap.querySelector(".dica");
  if (!dica) {
    dica = document.createElement("div");
    dica.className = "dica";
    dica.setAttribute("role", "status");
    wrap.appendChild(dica);
  }

  const mover = (ev) => {
    const r = canvas.getBoundingClientRect();
    const ponto = ev.touches ? ev.touches[0] : ev;
    const mx = ponto.clientX - r.left;
    const my = ponto.clientY - r.top;
    const item = achar(mx, my);
    if (!item) { dica.classList.remove("on"); return; }
    dica.textContent = texto(item);
    dica.classList.add("on");
    const lg = dica.offsetWidth;
    dica.style.left = `${Math.max(0, Math.min(mx - lg / 2, r.width - lg))}px`;
    dica.style.top = `${Math.max(0, my - 38)}px`;
  };
  const sair = () => dica.classList.remove("on");

  canvas.onpointermove = mover;
  canvas.onpointerdown = mover;
  canvas.onpointerleave = sair;
  canvas.onpointercancel = sair;
}
