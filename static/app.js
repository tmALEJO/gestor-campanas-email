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
  if (t === "generar") cargarOpciones();
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
["#f-genericos", "#f-verificados"].forEach((s) => ($(s).onchange = actualizarConteo));
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
  $("#g-nombre").value = ""; $("#c-nombre").value = ""; $("#c-archivo").value = "";
  $("#resultado").hidden = true;
  cargarOpciones();
};

// ================================================================ generar / completar
$("#btn-generar").onclick = (ev) => conCarga(ev.target, async () => {
  const f = filtros();
  const cantidad = Number($("#g-cantidad").value) || 0;
  const r = await postJSON("/api/generar", { ...f, cantidad, nombre: $("#g-nombre").value });
  mostrarResultado(r, "Archivo generado");
  cargarOpciones();
});

$("#btn-completar").onclick = (ev) => conCarga(ev.target, async () => {
  const archivo = $("#c-archivo").files[0];
  if (!archivo) throw new Error("Sube el archivo de correos buenos.");
  const fd = new FormData();
  fd.append("archivos", archivo);
  fd.append("cantidad", $("#c-cantidad").value || "0");
  fd.append("nombre", $("#c-nombre").value);
  fd.append("filtros", JSON.stringify(filtros()));
  const r = await api("/api/completar", { method: "POST", body: fd });
  mostrarResultado(r, "Archivo completado");
  $("#c-archivo").value = "";
  cargarOpciones();
});

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
