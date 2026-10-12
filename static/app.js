// ================================================================ utilidades
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const fmt = (n) => Number(n || 0).toLocaleString("es-CO");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ESTADOS = { disponible: "Disponibles", usado: "Usados", invalido: "Inválidos", baja: "Bajas" };

async function api(url, opts = {}) {
  const r = await fetch(url, opts);
  const tipo = r.headers.get("content-type") || "";
  const datos = tipo.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error(datos.error || datos || r.statusText);
  return datos;
}
const postJSON = (url, cuerpo) => api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) });

function toast(msg, error = false) {
  const d = document.createElement("div");
  d.textContent = msg;
  if (error) d.className = "error";
  $("#toast").appendChild(d);
  setTimeout(() => d.remove(), error ? 7000 : 3500);
}

async function conCarga(boton, fn) {
  const txt = boton.textContent;
  boton.disabled = true;
  boton.textContent = "Procesando…";
  try { return await fn(); }
  catch (e) { toast(e.message, true); }
  finally { boton.disabled = false; boton.textContent = txt; }
}

function tabla(cols, filas) {
  if (!filas.length) return '<p class="muted">Sin datos.</p>';
  const cab = cols.map((c) => `<th class="${c.n ? "n" : ""}">${c.t}</th>`).join("");
  const cuerpo = filas.map((f) => "<tr>" + cols.map((c) => `<td class="${c.n ? "n" : ""}">${c.f ? c.f(f) : esc(f[c.k])}</td>`).join("") + "</tr>").join("");
  return `<div class="tabla-scroll"><table><thead><tr>${cab}</tr></thead><tbody>${cuerpo}</tbody></table></div>`;
}
const barra = (v, max) => `<div class="barra"><i style="width:${max ? (100 * v) / max : 0}%"></i></div>`;

// ================================================================ pestañas
$$("#tabs button").forEach((b) => (b.onclick = () => mostrarTab(b.dataset.tab)));
function mostrarTab(t) {
  $$("#tabs button").forEach((b) => b.classList.toggle("activo", b.dataset.tab === t));
  $$(".tab").forEach((s) => s.classList.toggle("activo", s.id === "tab-" + t));
  if (t === "resumen") cargarResumen();
  if (t === "generar") { cargarOpciones(); cargarCB(); retomarBorrador(); }
  if (t === "lotes") cargarLotes();
  if (t === "base") cargarBase();
}

// ================================================================ resumen
async function cargarResumen() {
  try {
    const d = await api("/api/resumen");
    const colores = { disponible: "var(--disp)", usado: "var(--usado)", invalido: "var(--inv)", baja: "var(--baja)" };
    $("#cards").innerHTML =
      `<div class="card"><b>${fmt(d.total)}</b><span>Total en la base</span></div>` +
      Object.entries(ESTADOS).map(([k, t]) => `<div class="card" style="--c:${colores[k]}"><b>${fmt(d.estados[k])}</b><span>${t}</span></div>`).join("") +
      `<div class="card"><b>${fmt(d.verificados)}</b><span>Verificados buenos</span></div>` +
      `<div class="card"><b>${fmt(d.lotes)}</b><span>Lotes generados</span></div>`;
    const cols = (titulo) => {
      const max = Math.max(...d[titulo].map((x) => x.disponible), 1);
      return [
        { t: "Nombre", k: "nombre" },
        { t: "Disponibles", n: 1, f: (x) => fmt(x.disponible) },
        { t: "", f: (x) => barra(x.disponible, max) },
        { t: "Usados", n: 1, f: (x) => fmt(x.usado) },
        { t: "Inválidos", n: 1, f: (x) => fmt(x.invalido) },
        { t: "Bajas", n: 1, f: (x) => fmt(x.baja) },
        { t: "Total", n: 1, f: (x) => fmt(x.total) },
      ];
    };
    $("#t-seccion").innerHTML = tabla(cols("por_seccion"), d.por_seccion);
    $("#t-pais").innerHTML = tabla(cols("por_pais"), d.por_pais);
    $("#t-proveedor").innerHTML = tabla(cols("por_proveedor"), d.por_proveedor);
    $("#t-dominios").innerHTML = tabla([{ t: "Dominio", k: "nombre" }, { t: "Disponibles", n: 1, f: (x) => fmt(x.disponible) }], d.top_dominios);
    $("#sub").textContent = d.excels.length ? `Nariñotex · ${d.excels.join(", ")}` : "Nariñotex · ⚠ no hay Excel en data/";
  } catch (e) { toast(e.message, true); }
}

// ================================================================ generar: filtros
const F = { paises: new Set(), proveedores: new Set(), secciones: new Map(), modo: "azar" };
let OPC = null;

async function cargarOpciones() {
  try {
    OPC = await api("/api/opciones");
    pintarChips("#f-paises", OPC.paises, F.paises);
    pintarChips("#f-proveedores", OPC.proveedores, F.proveedores);
    pintarSecciones();
    actualizarConteo();
  } catch (e) { toast(e.message, true); }
}

function pintarChips(sel, lista, conjunto) {
  $(sel).innerHTML = lista.map((o, i) =>
    `<label class="chip ${conjunto.has(o.nombre) ? "on" : ""}"><input type="checkbox" data-i="${i}" ${conjunto.has(o.nombre) ? "checked" : ""}>${esc(o.nombre)} <em>${fmt(o.disponible)}</em></label>`).join("");
  $(sel).querySelectorAll("input").forEach((inp) => (inp.onchange = () => {
    const nombre = lista[inp.dataset.i].nombre;
    inp.checked ? conjunto.add(nombre) : conjunto.delete(nombre);
    inp.parentElement.classList.toggle("on", inp.checked);
    actualizarConteo();
  }));
}

function pintarSecciones() {
  const cont = $("#f-secciones");
  cont.classList.toggle("sin-valor", F.modo === "azar");
  cont.innerHTML = OPC.secciones.map((s, i) => {
    const on = F.secciones.has(s.nombre);
    return `<div class="fila-sec">
      <label><input type="checkbox" data-i="${i}" ${on ? "checked" : ""}>${esc(s.nombre)}</label>
      <span class="disp" data-disp="${i}">${fmt(s.disponible)}</span>
      <input type="number" min="0" data-v="${i}" placeholder="${F.modo === "porcentaje" ? "%" : "cant."}" value="${on ? F.secciones.get(s.nombre) ?? "" : ""}" ${on ? "" : "disabled"}>
    </div>`;
  }).join("");
  cont.querySelectorAll("input[type=checkbox]").forEach((c) => (c.onchange = () => {
    const nombre = OPC.secciones[c.dataset.i].nombre;
    const v = cont.querySelector(`[data-v="${c.dataset.i}"]`);
    if (c.checked) F.secciones.set(nombre, v.value); else F.secciones.delete(nombre);
    v.disabled = !c.checked;
    actualizarConteo();
  }));
  cont.querySelectorAll("input[type=number]").forEach((v) => (v.oninput = () => {
    F.secciones.set(OPC.secciones[v.dataset.v].nombre, v.value);
    sumaValores();
  }));
  sumaValores();
}

function sumaValores() {
  const suma = [...F.secciones.values()].reduce((a, b) => a + (Number(b) || 0), 0);
  notaCreditos();
  $("#suma-valores").textContent =
    F.modo === "porcentaje" && F.secciones.size ? `Suma: ${suma}% ${suma !== 100 ? "(se ajusta proporcionalmente)" : "✓"}` :
    F.modo === "cantidad" && F.secciones.size ? `Total: ${fmt(suma)} correos` : "";
  $("#g-nota-cantidad").hidden = F.modo !== "cantidad";
}

function filtros() {
  return {
    paises: [...F.paises], proveedores: [...F.proveedores], modo: F.modo,
    secciones: [...F.secciones].map(([nombre, valor]) => ({ nombre, valor: Number(valor) || 0 })),
    excluir_genericos: $("#f-genericos").checked,
    solo_verificados: $("#f-verificados").checked,
    excluir_dudosos: $("#f-dudosos").checked,
    rellenar: $("#f-rellenar").checked,
  };
}

let tConteo;
function actualizarConteo() {
  clearTimeout(tConteo);
  tConteo = setTimeout(async () => {
    try {
      const r = await postJSON("/api/contar", filtros());
      $("#disp-filtros").textContent = fmt(r.total);
      OPC.secciones.forEach((s, i) => {
        const el = document.querySelector(`[data-disp="${i}"]`);
        if (el) el.textContent = fmt(r.por_seccion[s.nombre] || 0);
      });
    } catch (e) { toast(e.message, true); }
  }, 200);
}

$$("input[name=modo]").forEach((r) => (r.onchange = () => { F.modo = r.value; pintarSecciones(); }));
["#f-genericos", "#f-verificados", "#f-dudosos"].forEach((s) => ($(s).onchange = actualizarConteo));
$("#sec-todas").onclick = () => { OPC.secciones.forEach((s) => F.secciones.set(s.nombre, F.secciones.get(s.nombre) ?? "")); pintarSecciones(); actualizarConteo(); };
$("#sec-ninguna").onclick = () => { F.secciones.clear(); pintarSecciones(); actualizarConteo(); };
$("#sec-parejo").onclick = () => {
  if (!F.secciones.size) return toast("Primero marca las secciones.", true);
  const n = F.secciones.size;
  if (F.modo === "cantidad") {
    const total = Number($("#g-cantidad").value) || 0;
    [...F.secciones.keys()].forEach((k, i) => F.secciones.set(k, Math.floor(total / n) + (i < total % n ? 1 : 0)));
  } else {
    if (F.modo === "azar") { F.modo = "porcentaje"; $("input[name=modo][value=porcentaje]").checked = true; }
    const base = Math.floor(100 / n);
    [...F.secciones.keys()].forEach((k, i) => F.secciones.set(k, base + (i < 100 - base * n ? 1 : 0)));
  }
  pintarSecciones();
};
$("#btn-limpiar").onclick = () => {
  F.paises.clear(); F.proveedores.clear(); F.secciones.clear(); F.modo = "azar";
  $("input[name=modo][value=azar]").checked = true;
  $("#f-genericos").checked = false; $("#f-verificados").checked = false; $("#f-rellenar").checked = true;
  $("#f-dudosos").checked = true;
  $("#g-nombre").value = ""; $("#c-nombre").value = ""; $("#c-archivo").value = "";
  $("#resultado").hidden = true;
  cargarOpciones();
};

// ================================================================ ClearBounce: créditos
let CB = { configurado: false, creditos: null };

async function cargarCB(refrescar = true) {
  try {
    CB = await api("/api/clearbounce/estado?refrescar=" + (refrescar ? 1 : 0));
  } catch (e) { CB = { configurado: false, creditos: null, error: e.message }; }
  pintarCB();
}

function pintarCB() {
  const b = $("#cb-badge");
  const n = CB.creditos;
  b.className = "cb-badge " + (!CB.configurado ? "off" : CB.error && n == null ? "err" : n != null && n < 50 ? "bajo" : "ok");
  b.querySelector("span").textContent = !CB.configurado ? "ClearBounce sin configurar"
    : n == null ? "ClearBounce · ? créditos" : `ClearBounce · ${fmt(n)} créditos`;
  b.title = CB.error ? CB.error : CB.actualizado ? `Actualizado ${CB.actualizado} · clic para refrescar` : "Clic para refrescar";
  $("#cb-creditos").textContent = !CB.configurado ? "—" : n == null ? "?" : fmt(n);
  $("#cb-stat").classList.toggle("off", !CB.configurado);
  notaCreditos();
}
$("#cb-badge").onclick = () => cargarCB();
$("#cb-refrescar").onclick = () => cargarCB();

function cantidadEfectiva() {
  if (F.modo === "cantidad" && F.secciones.size) return [...F.secciones.values()].reduce((a, b) => a + (Number(b) || 0), 0);
  return Number($("#g-cantidad").value) || 0;
}

function notaCreditos() {
  const el = $("#g-creditos-nota");
  if (!el) return;
  const cant = cantidadEfectiva();
  if (!CB.configurado) {
    el.hidden = false; el.className = "nota-cb off";
    el.innerHTML = `ClearBounce no está configurado: falta <code>CLEARBOUNCE_API_KEY</code> en el archivo <code>.env</code>. Podrás generar sin verificar.`;
    return;
  }
  if (CB.creditos == null || !cant) { el.hidden = true; return; }
  el.hidden = false;
  if (cant <= CB.creditos) {
    el.className = "nota-cb ok";
    el.innerHTML = `✓ Te alcanza: verificar ${fmt(cant)} correos usa hasta ${fmt(cant)} de tus ${fmt(CB.creditos)} créditos <span class="muted">(los ya verificados hace poco no se cobran).</span>`;
  } else {
    el.className = "nota-cb mal";
    el.innerHTML = `⚠ Tienes ${fmt(CB.creditos)} créditos. Puedes generar ${fmt(cant)}, pero solo verificar ${fmt(CB.creditos)}. Baja la cantidad o recarga créditos.`;
  }
}
$("#g-cantidad").addEventListener("input", notaCreditos);

// ================================================================ generar / completar (con vista previa)
$("#btn-generar").onclick = (ev) => conCarga(ev.target, async () => {
  const cantidad = Number($("#g-cantidad").value) || 0;
  const b = await postJSON("/api/borradores", { ...filtros(), cantidad, nombre: $("#g-nombre").value });
  $("#resultado").hidden = true;
  pintarBorrador(b, true);
});

$("#btn-completar").onclick = (ev) => conCarga(ev.target, async () => {
  const archivo = $("#c-archivo").files[0];
  if (!archivo) throw new Error("Sube el archivo de correos buenos.");
  const fd = new FormData();
  fd.append("archivos", archivo);
  fd.append("cantidad", $("#c-cantidad").value || "0");
  fd.append("nombre", $("#c-nombre").value);
  fd.append("filtros", JSON.stringify(filtros()));
  if ($("#c-verificar").checked) {
    const b = await api("/api/borradores/completar", { method: "POST", body: fd });
    $("#resultado").hidden = true;
    pintarBorrador(b, true);
  } else {
    const r = await api("/api/completar", { method: "POST", body: fd });
    $("#borrador").hidden = true;
    mostrarResultado(r, "Archivo completado");
    cargarOpciones();
  }
  $("#c-archivo").value = "";
});

// ================================================================ borrador / verificación
const MOTIVOS = {
  accepted_email: "aceptado", rejected_email: "el buzón no existe", invalid_domain: "dominio sin servidor de correo",
  invalid_syntax: "formato inválido", low_quality: "baja calidad (desechable, genérico o con typo)",
  low_deliverability: "catch-all (el dominio acepta todo)", unavailable_smtp: "el servidor no respondió",
  unsupported: "servidor no soportado / greylisting", unknown: "desconocido", risky: "riesgoso",
};
const motivo = (m) => MOTIVOS[m] || m || "—";
const POLITICA_TXT = {
  fuera: "Dejarlos fuera del archivo (siguen en la base, pero no se vuelven a escoger)",
  catchall: "Incluir solo los catch-all (dominios corporativos que aceptan todo)",
  incluir: "Incluir todos los dudosos en el archivo",
  invalidar: "Marcarlos como inválidos",
};
let BORR = null, tPoll = null, tReloj = null, politica = "fuera";

async function retomarBorrador() {
  if (BORR && !$("#borrador").hidden) return;
  try {
    const b = await api("/api/borradores/pendiente");
    if (b) pintarBorrador(b);
  } catch (e) { /* sin borrador pendiente */ }
}

function finalEstimado(b) {
  const g = b.grupos;
  const dud = politica === "incluir" ? g.dudoso : politica === "catchall" ? b.dudosos_catchall : 0;
  const nuevos = g.bueno + g.sin_verificar + dud;
  return { nuevos, total: g.base + nuevos };
}

function tarjeta(clase, num, titulo, sub = "") {
  return `<div class="res-card ${clase}"><b>${fmt(num)}</b><span>${titulo}</span>${sub ? `<small>${sub}</small>` : ""}</div>`;
}

function pintarBorrador(b, scroll = false) {
  BORR = b;
  clearTimeout(tPoll); clearInterval(tReloj);
  const box = $("#borrador");
  box.hidden = false;
  if (b.estado === "verificando") pintarVerificando(b);
  else if (b.estado === "generado" || b.estado === "descartado") { box.hidden = true; return; }
  else pintarRevision(b);
  if (scroll) box.scrollIntoView({ behavior: "smooth", block: "start" });
}

function cabeceraBorrador(b, titulo) {
  return `<div class="cab-panel"><h3>${titulo} · borrador #${b.id}${b.nombre ? ` · ${esc(b.nombre)}` : ""}</h3>
    <span class="muted">${b.tipo === "completado" ? "Completar archivo" : "Archivo nuevo"} · ${esc(b.fecha)}</span></div>`;
}

function pintarVerificando(b) {
  const v = b.verificacion || { porcentaje: 0, procesados: 0, total: b.a_verificar, en_vivo: {}, segundos: 0 };
  const vivo = v.en_vivo || {};
  const inicio = Date.now() - (v.segundos || 0) * 1000;
  $("#borrador").innerHTML = cabeceraBorrador(b, "Verificando con ClearBounce") + `
    <div class="verif">
      <div class="spinner"></div>
      <div class="crece">
        <div class="verif-txt"><b id="v-pct">${v.porcentaje}%</b> · <span id="v-cuenta">${fmt(v.procesados)} de ${fmt(v.total)} correos revisados</span></div>
        <div class="progreso"><i id="v-barra" style="width:${Math.max(3, v.porcentaje)}%"></i></div>
        <div class="muted"><span id="v-reloj">0:00</span> transcurrido · <span id="v-falta"></span></div>
      </div>
    </div>
    <div class="chips-vivo">
      <span class="tag disponible">${fmt(vivo.deliverable)} buenos</span>
      <span class="tag invalido">${fmt(vivo.undeliverable)} malos</span>
      <span class="tag dudoso">${fmt((vivo.risky || 0) + (vivo.unknown || 0))} dudosos</span>
    </div>
    <p class="muted">No cierres el programa (la ventana negra). Puedes recargar la página o cambiar de pestaña: al volver a <b>Generar</b> se retoma.</p>`;
  const tick = () => {
    const seg = Math.floor((Date.now() - inicio) / 1000);
    $("#v-reloj").textContent = reloj(seg);
    let falta = null;
    if (v.porcentaje > 2 && v.porcentaje < 100) falta = Math.round(seg * (100 - v.porcentaje) / v.porcentaje);
    else if (v.estimado) falta = Math.max(0, v.estimado - seg);
    $("#v-falta").textContent = falta != null ? `faltan ~${reloj(falta)}` : "calculando…";
  };
  tick();
  tReloj = setInterval(tick, 1000);
  tPoll = setTimeout(sondear, 4000);
}
const reloj = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

async function sondear() {
  if (!BORR) return;
  try {
    const b = await api(`/api/borradores/${BORR.id}/progreso`);
    if (b.estado !== "verificando") {
      toast(`Verificación terminada: ${fmt(b.grupos.bueno)} buenos, ${fmt(b.grupos.malo)} malos, ${fmt(b.grupos.dudoso)} dudosos.`);
      cargarCB(); actualizarConteo();
    }
    pintarBorrador(b);
  } catch (e) {
    toast(e.message, true);
    tPoll = setTimeout(sondear, 8000); // reintenta
  }
}

function pintarRevision(b) {
  const g = b.grupos;
  const verificado = b.verificado_alguna_vez;
  const fin = finalEstimado(b);
  const faltan = Math.max(0, b.pedidos - fin.nuevos);
  const sinCred = CB.configurado && CB.creditos != null && CB.creditos < b.a_verificar;
  const desglose = Object.entries(b.desglose || {}).sort((x, y) => y[1] - x[1]);
  const titulo = !verificado ? "Vista previa" : b.a_verificar ? "Verificación parcial" : "Verificación lista";

  let html = cabeceraBorrador(b, titulo);
  html += (b.avisos || []).map((a) => `<div class="aviso">${esc(a)}</div>`).join("");
  if (b.error) html += `<div class="aviso error">${esc(b.error)}</div>`;

  // --- tarjetas
  html += `<div class="res-cards">`;
  if (g.base) html += tarjeta("base", g.base, "Buenos del archivo subido", "no se verifican de nuevo");
  if (verificado) {
    html += tarjeta("bueno", g.bueno, "Buenos", "listos para enviar");
    html += tarjeta("malo", g.malo, "Malos", g.malo ? "✓ ya marcados como inválidos" : "ninguno");
    html += tarjeta("dudoso", g.dudoso, "Dudosos", "riesgosos o desconocidos");
    if (g.sin_verificar) html += tarjeta("pend", g.sin_verificar, "Sin verificar", "todavía no pasan por ClearBounce");
  } else {
    html += tarjeta("pend", b.nuevos, "Correos seleccionados", `pediste ${fmt(b.pedidos)}`);
  }
  html += `</div>`;

  html += `<div class="grid2 rev">`;
  // --- columna izquierda: detalle
  html += `<div>`;
  if (desglose.length) html += `<details ${verificado ? "" : "open"}><summary>Por sección (${desglose.length})</summary>${tabla([{ t: "Sección", f: (x) => esc(x[0]) }, { t: "Correos", n: 1, f: (x) => fmt(x[1]) }], desglose)}</details>`;
  if (b.malos.length) html += `<details open><summary class="t-malo">Malos · marcados como inválidos (${fmt(g.malo)})</summary>
      ${tabla([{ t: "Correo", k: "email" }, { t: "Motivo", f: (x) => `<span class="muted">${esc(motivo(x.motivo))}</span>` }], b.malos)}</details>`;
  if (b.dudosos.length) html += `<details ${b.malos.length ? "" : "open"}><summary class="t-dudoso">Dudosos (${fmt(g.dudoso)})</summary>
      <p class="muted">${Object.entries(b.motivos_dudosos).map(([k, n]) => `${esc(motivo(k))}: <b>${fmt(n)}</b>`).join(" · ")}</p>
      ${tabla([{ t: "Correo", k: "email" }, { t: "Motivo", f: (x) => `<span class="muted">${esc(motivo(x.motivo))}</span>` }, { t: "Puntaje", n: 1, f: (x) => x.puntaje ?? "" }], b.dudosos)}</details>`;
  if (verificado) html += `<p><a class="btn sec peq" href="/api/borradores/${b.id}/reporte">Descargar reporte completo de la verificación (CSV)</a></p>`;
  html += `</div>`;

  // --- columna derecha: acciones
  html += `<div class="acciones-borr">`;
  if (b.a_verificar) {
    html += `<div class="caja-cb">
      <h4>Verificar con ClearBounce</h4>
      <p>${fmt(b.a_verificar)} correos por verificar = <b>${fmt(b.a_verificar)} créditos</b>.
      ${CB.creditos != null ? `Tienes <b>${fmt(CB.creditos)}</b> → te quedarían <b>${fmt(Math.max(0, CB.creditos - b.a_verificar))}</b>.` : ""}</p>
      ${b.reutilizados ? `<p class="muted">${fmt(b.reutilizados)} ya se habían verificado hace poco: se reutiliza su resultado sin gastar créditos.</p>` : ""}
      ${!CB.configurado ? `<div class="aviso">Falta la API key en <code>.env</code>. Puedes generar sin verificar.</div>` : ""}
      ${sinCred ? `<div class="aviso error">No te alcanzan los créditos. Descarta y genera menos correos, o recarga en ClearBounce.</div>` : ""}
      <button class="pri" id="b-verificar" ${!CB.configurado || sinCred ? "disabled" : ""}>Verificar ${fmt(b.a_verificar)} correos</button>
    </div>`;
  }
  if (verificado && (g.dudoso || 0) > 0) {
    html += `<h4>¿Qué hago con los ${fmt(g.dudoso)} dudosos?</h4><div class="politicas">` +
      Object.entries(POLITICA_TXT).filter(([k]) => k !== "catchall" || b.dudosos_catchall)
        .map(([k, t]) => `<label class="check"><input type="radio" name="politica" value="${k}" ${politica === k ? "checked" : ""}> ${t}${k === "catchall" ? ` (${fmt(b.dudosos_catchall)})` : ""}</label>`).join("") + `</div>`;
  }
  if (verificado && faltan > 0 && !b.a_verificar) {
    html += `<div class="caja-reponer">
      <p>Pediste <b>${fmt(b.pedidos)}</b> y quedan <b>${fmt(fin.nuevos)}</b> buenos. ¿Reponer los que faltan?</p>
      <div class="fila"><label>Cantidad<input type="number" id="b-reponer-n" min="1" value="${faltan}"></label></div>
      <button class="sec" id="b-reponer" ${!CB.configurado ? "disabled" : ""}>Reponer y verificar</button>
      <p class="muted">Escoge nuevos con los mismos filtros (sin repetir) y los pasa por ClearBounce.</p>
    </div>`;
  }
  html += `<div class="final">
      <p>El archivo tendrá <b id="b-final">${fmt(fin.total)}</b> correos${g.base ? ` (${fmt(g.base)} subidos + <span id="b-final-n">${fmt(fin.nuevos)}</span> nuevos)` : ""}.
      ${g.sin_verificar && verificado ? `<br><span class="muted">Incluye ${fmt(g.sin_verificar)} sin verificar.</span>` : ""}</p>
      <button class="pri" id="b-confirmar">${verificado ? "Generar archivo y marcar como usados" : "Generar sin verificar"}</button>
      <button class="sec peligro" id="b-descartar">Descartar</button>
    </div>`;
  html += `</div></div>`;
  $("#borrador").innerHTML = html;

  $$("input[name=politica]").forEach((r) => (r.onchange = () => {
    politica = r.value;
    const f = finalEstimado(BORR);
    $("#b-final").textContent = fmt(f.total);
    if ($("#b-final-n")) $("#b-final-n").textContent = fmt(f.nuevos);
    if ($("#b-reponer-n")) $("#b-reponer-n").value = Math.max(1, BORR.pedidos - f.nuevos);
  }));
  if ($("#b-verificar")) $("#b-verificar").onclick = (ev) => conCarga(ev.target, async () => {
    pintarBorrador(await api(`/api/borradores/${b.id}/verificar`, { method: "POST" }));
    cargarCB();
  });
  if ($("#b-reponer")) $("#b-reponer").onclick = (ev) => conCarga(ev.target, async () => {
    const n = Number($("#b-reponer-n").value) || 0;
    if (CB.creditos != null && n > CB.creditos) throw new Error(`Solo tienes ${fmt(CB.creditos)} créditos: repón ${fmt(CB.creditos)} o menos.`);
    const r = await postJSON(`/api/borradores/${b.id}/reponer`, { cantidad: n });
    if (!r.a_verificar) return pintarBorrador(r);
    try {
      pintarBorrador(await api(`/api/borradores/${b.id}/verificar`, { method: "POST" }));
      cargarCB();
    } catch (e) { pintarBorrador(r); throw e; }
  });
  $("#b-confirmar").onclick = (ev) => conCarga(ev.target, async () => {
    if (!verificado && CB.configurado && !confirm("¿Generar SIN verificar con ClearBounce? Los correos quedarán marcados como usados.")) return;
    const r = await postJSON(`/api/borradores/${b.id}/confirmar`, { dudosos: politica });
    $("#borrador").hidden = true; BORR = null; politica = "fuera";
    mostrarResultado(r, r.clearbounce ? "Archivo verificado y generado" : "Archivo generado");
    cargarOpciones();
  });
  $("#b-descartar").onclick = (ev) => conCarga(ev.target, async () => {
    if (!confirm("¿Descartar este borrador? No se marca nada como usado (los malos ya detectados siguen como inválidos).")) return;
    await api(`/api/borradores/${b.id}/descartar`, { method: "POST" });
    $("#borrador").hidden = true; BORR = null; politica = "fuera";
    toast("Borrador descartado.");
    actualizarConteo();
  });
}

function enlaces(id, extras) {
  const x = extras ? 1 : 0;
  return `<a class="btn pri" href="/api/lotes/${id}/descargar?formato=csv&extras=${x}">Descargar CSV (Brevo)</a>
          <a class="btn sec" href="/api/lotes/${id}/descargar?formato=xlsx&extras=${x}">Descargar Excel</a>`;
}

function mostrarResultado(r, titulo) {
  const box = $("#resultado");
  box.hidden = false;
  const desglose = Object.entries(r.desglose || {}).sort((a, b) => b[1] - a[1]);
  box.innerHTML = `<h3>✓ ${titulo} · lote #${r.lote_id}</h3>
    <p><b>${fmt(r.total)}</b> correos en el archivo${r.base ? ` (${fmt(r.base)} que subiste + ${fmt(r.nuevos)} nuevos)` : ""}. Los nuevos ya quedaron marcados como <span class="tag usado">usado</span>.</p>
    ${(r.avisos || []).map((a) => `<div class="aviso">${esc(a)}</div>`).join("")}
    ${desglose.length ? tabla([{ t: "Sección", f: (x) => esc(x[0]) }, { t: "Nuevos", n: 1, f: (x) => fmt(x[1]) }], desglose) : ""}
    <label class="check"><input type="checkbox" id="r-extras"> Incluir columnas extra (nombre, empresa, sección, país, ciudad)</label>
    <div class="mini-acc" id="r-links">${enlaces(r.lote_id, false)}</div>
    ${r.borrador_id && r.clearbounce ? `<p><a class="btn sec peq" href="/api/borradores/${r.borrador_id}/reporte">Reporte de verificación (CSV)</a></p>` : ""}
    <p class="muted">También se guardó una copia en <code>exports/${esc(r.copia)}</code>.</p>`;
  $("#r-extras").onchange = (e) => ($("#r-links").innerHTML = enlaces(r.lote_id, e.target.checked));
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// ================================================================ marcar
function formMarcar(confirmar) {
  const files = $("#m-archivos").files;
  if (!files.length) throw new Error("Selecciona al menos un archivo.");
  const fd = new FormData();
  [...files].forEach((f) => fd.append("archivos", f));
  fd.append("palabra", $("#m-palabra").value);
  fd.append("estado", $("#m-estado").value);
  fd.append("motivo", $("#m-motivo").value);
  fd.append("confirmar", confirmar ? "1" : "0");
  return fd;
}
["#m-archivos", "#m-palabra", "#m-estado"].forEach((s) => $(s).addEventListener("input", () => ($("#btn-confirmar").disabled = true)));

$("#btn-prev").onclick = (ev) => conCarga(ev.target, async () => {
  const r = await api("/api/marcar", { method: "POST", body: formMarcar(false) });
  const estado = $("#m-estado").selectedOptions[0].textContent;
  $("#m-res").innerHTML = `<h3>Vista previa</h3>
    <p>Filas con correo: <b>${fmt(r.filas_con_correo)}</b> · filas tomadas: <b>${fmt(r.filas_tomadas)}</b> · correos únicos: <b>${fmt(r.correos)}</b></p>
    ${!$("#m-palabra").value.trim() && $("#m-estado").value === "invalido" ? '<div class="aviso">Se tomarán TODAS las filas. Si el archivo trae buenos y malos juntos, escribe la palabra de estado (ej: invalid) y vuelve a previsualizar.</div>' : ""}
    <h4>Estado actual de esos correos</h4>
    ${tabla([{ t: "Estado", f: (x) => esc(x[0]) }, { t: "Correos", n: 1, f: (x) => fmt(x[1]) }], Object.entries(r.por_estado_actual))}
    <h4>Muestra</h4><p class="muted">${r.muestra.map(esc).join("<br>")}</p>
    <p>Se marcarán como: <b>${esc(estado)}</b></p>`;
  $("#btn-confirmar").disabled = r.correos === 0;
});

$("#btn-confirmar").onclick = (ev) => conCarga(ev.target, async () => {
  const r = await api("/api/marcar", { method: "POST", body: formMarcar(true) });
  $("#m-res").innerHTML = `<h3>✓ Listo</h3>
    <p>Recibidos: <b>${fmt(r.recibidos)}</b><br>Actualizados: <b>${fmt(r.actualizados)}</b><br>
    Ya tenían ese estado: <b>${fmt(r.ya_estaban)}</b><br>
    Conservados (ya tenían un estado más fuerte, ej. baja): <b>${fmt(r.conservados)}</b><br>
    No estaban en la base y se registraron igual: <b>${fmt(r.registrados)}</b></p>`;
  $("#m-archivos").value = ""; $("#btn-confirmar").disabled = true;
  toast("Correos marcados.");
});

// ================================================================ lotes
async function cargarLotes() {
  try {
    const lotes = await api("/api/lotes");
    const extras = $("#l-extras").checked ? 1 : 0;
    const resumenFiltros = (f) => {
      if (!f) return "";
      const p = [];
      if (f.paises?.length) p.push(f.paises.join(", "));
      if (f.proveedores?.length) p.push(f.proveedores.join(", "));
      if (f.secciones?.length) p.push(f.secciones.map((s) => s.nombre + (f.modo !== "azar" ? ` (${s.valor}${f.modo === "porcentaje" ? "%" : ""})` : "")).join(", "));
      if (f.excluir_genericos) p.push("sin genéricos");
      return p.join(" · ") || "todos";
    };
    $("#t-lotes").innerHTML = tabla([
      { t: "#", k: "id" },
      { t: "Fecha", k: "fecha" },
      { t: "Tipo", f: (l) => esc(l.tipo) + (l.anulado ? ' <span class="tag invalido">anulado</span>' : "") },
      { t: "Nombre", f: (l) => esc(l.nombre || "") + (l.nota ? `<br><span class="muted">${esc(l.nota)}</span>` : "") },
      { t: "Correos", n: 1, f: (l) => fmt(l.cantidad) },
      { t: "Filtros", f: (l) => `<span class="muted">${esc(resumenFiltros(l.filtros))}</span>` },
      { t: "", f: (l) => l.tipo === "generado" || l.tipo === "completado" ? `
          <a class="btn sec peq" href="/api/lotes/${l.id}/descargar?formato=csv&extras=${extras}">CSV</a>
          <a class="btn sec peq" href="/api/lotes/${l.id}/descargar?formato=xlsx&extras=${extras}">Excel</a>
          ${l.anulado ? "" : `<button class="sec peq peligro" data-anular="${l.id}">Anular</button>`}` : "" },
    ], lotes);
    $$("[data-anular]").forEach((b) => (b.onclick = () => conCarga(b, async () => {
      if (!confirm(`¿Anular el lote #${b.dataset.anular}? Sus correos nuevos vuelven a estar disponibles. Hazlo solo si NO lo subiste a Brevo.`)) return;
      const r = await api(`/api/lotes/${b.dataset.anular}/anular`, { method: "POST" });
      toast(`${fmt(r.liberados)} correos volvieron a disponibles.`);
      cargarLotes();
    })));
  } catch (e) { toast(e.message, true); }
}
$("#l-extras").onchange = cargarLotes;

// ================================================================ buscar
let tBuscar;
$("#b-q").oninput = () => {
  clearTimeout(tBuscar);
  tBuscar = setTimeout(buscar, 300);
};
async function buscar() {
  try {
    const filas = await api("/api/buscar?q=" + encodeURIComponent($("#b-q").value));
    $("#t-buscar").innerHTML = tabla([
      { t: "Correo", k: "email" },
      { t: "Estado", f: (r) => `<span class="tag ${r.estado}">${r.estado}</span>${r.verificado ? " ✓" : ""}` },
      { t: "Sección", k: "seccion" }, { t: "País", k: "pais" }, { t: "Empresa", k: "empresa" },
      { t: "Motivo", f: (r) => `<span class="muted">${esc(r.motivo || "")}</span>` },
      { t: "Cambiar a", f: (r) => `<select data-email="${esc(r.email)}">${Object.keys(ESTADOS).map((k) => `<option ${k === r.estado ? "selected" : ""}>${k}</option>`).join("")}</select>` },
    ], filas);
    $$("#t-buscar select").forEach((s) => (s.onchange = async () => {
      try {
        await postJSON("/api/estado_manual", { email: s.dataset.email, estado: s.value });
        toast(`${s.dataset.email} → ${s.value}`);
        buscar();
      } catch (e) { toast(e.message, true); }
    }));
  } catch (e) { toast(e.message, true); }
}

// ================================================================ base
function pintarReporte(rep) {
  if (!rep) return '<p class="muted">Aún no se ha importado.</p>';
  return `<h4>Última importación · ${esc(rep.fecha)}</h4>
    ${tabla([{ t: "Dato", f: (x) => x[0] }, { t: "", n: 1, f: (x) => fmt(x[1]) }], [
      ["Filas leídas", rep.filas], ["Celdas de correo vacías", rep.celdas_vacias],
      ["Correos encontrados", rep.correos_encontrados], ["Dominios corregidos (gmial→gmail…)", rep.corregidos],
      ["Descartados por inválidos", rep.invalidos], ["Duplicados (entre hojas)", rep.duplicados],
      ["Válidos únicos", rep.validos_unicos], ["Nuevos en la base", rep.nuevos_en_base],
    ])}
    ${rep.hojas_omitidas?.length ? `<div class="aviso">Hojas sin columna de correo (omitidas): ${esc(rep.hojas_omitidas.join(", "))}</div>` : ""}
    <p class="muted">Los descartados quedaron en <code>exports/${esc(rep.reporte_invalidos || "")}</code> por si quieres revisarlos.</p>`;
}
async function cargarBase() {
  try {
    const d = await api("/api/resumen");
    $("#b-excels").innerHTML = d.excels.length ? "Archivos en data/: <b>" + d.excels.map(esc).join(", ") + "</b>" : "⚠ No hay ningún .xlsx en la carpeta data/";
    $("#b-reporte").innerHTML = pintarReporte(d.ultima_importacion);
  } catch (e) { toast(e.message, true); }
}
$("#btn-importar").onclick = (ev) => conCarga(ev.target, async () => {
  const rep = await api("/api/importar_excel", { method: "POST" });
  $("#b-reporte").innerHTML = pintarReporte(rep);
  toast("Base actualizada.");
});
$("#btn-sync").onclick = (ev) => conCarga(ev.target, async () => {
  const f = $("#s-archivo").files[0];
  if (!f) throw new Error("Elige el archivo exportado.");
  const fd = new FormData();
  fd.append("archivos", f);
  const r = await api("/api/importar_estado", { method: "POST", body: fd });
  $("#s-res").innerHTML = tabla([{ t: "Estado", f: (x) => x[0] }, { t: "Actualizados", n: 1, f: (x) => fmt(x[1].actualizados) }, { t: "Nuevos registrados", n: 1, f: (x) => fmt(x[1].registrados) }], Object.entries(r));
  toast("Estado importado.");
});

// ================================================================ inicio
cargarResumen();
cargarCB();
