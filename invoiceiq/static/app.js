// InvoiceIQ single-page UI. Vanilla JS, no build step. UI copy in Spanish (LatAm market).
"use strict";

const STATUS_LABEL = { processing: "Procesando", needs_review: "Requiere revisión", approved: "Aprobada" };
const SOURCE_LABEL = { rules: "Reglas", llm: "IA", human: "Manual" };
const AMOUNT_FIELDS = ["subtotal", "iva", "total"];
const $ = (sel) => document.querySelector(sel);
const cop = new Intl.NumberFormat("es-CO", { style: "currency", currency: "COP", minimumFractionDigits: 0, maximumFractionDigits: 2 });

const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* private mode */ } },
};
let token = store.get("iq_token");
let me = null;
let filter = "";
let current = null;
let authMode = "login";

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
const fmtMoney = (v) => (v == null || v === "" ? "—" : cop.format(Number(v)));
const fmtDate = (iso) => (iso ? iso.split("-").reverse().join("/") : "—");
const chip = (status) => `<span class="chip ${status}">${STATUS_LABEL[status] || status}</span>`;

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (opts.json !== undefined) { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(opts.json); }
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401 && token) { logout(); throw new Error("Sesión expirada"); }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail; } catch { /* not JSON */ }
    const err = new Error(typeof detail === "string" ? detail : detail?.message || "Error");
    err.status = res.status; err.detail = detail;
    throw err;
  }
  return res;
}

// ---------- Auth ----------
function setAuthMode(mode) {
  authMode = mode;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.mode === mode));
  document.querySelectorAll(".signup-only").forEach((el) => { el.hidden = mode !== "signup"; });
  $("#auth-submit").textContent = mode === "login" ? "Entrar" : "Crear cuenta";
}

async function submitAuth(e) {
  e.preventDefault();
  const form = new FormData(e.target);
  const body = { email: form.get("email"), password: form.get("password") };
  if (authMode === "signup") body.organization_name = form.get("organization_name");
  $("#auth-error").hidden = true;
  try {
    const res = await api(`/api/auth/${authMode}`, { method: "POST", json: body });
    const data = await res.json();
    token = data.access_token; store.set("iq_token", token);
    me = data.user; route();
  } catch (err) {
    $("#auth-error").textContent = err.status === 401 ? "Correo o contraseña incorrectos" : err.message;
    $("#auth-error").hidden = false;
  }
}

function logout() { token = null; me = null; store.set("iq_token", null); route(); }

// ---------- List ----------
async function loadList() {
  const all = await (await api("/api/invoices")).json();
  const count = (s) => all.filter((i) => i.status === s).length;
  $("#stats").innerHTML = [
    [all.length, "Facturas"], [count("needs_review"), "Requieren revisión"], [count("approved"), "Aprobadas"],
  ].map(([n, l]) => `<div class="stat"><b>${n}</b><span>${l}</span></div>`).join("");
  const rows = filter ? all.filter((i) => i.status === filter) : all;
  $("#empty").hidden = rows.length > 0;
  $("#invoice-rows").innerHTML = rows.map((i) => `
    <tr data-id="${esc(i.id)}">
      <td><strong>${esc(i.invoice_number || "—")}</strong><div class="muted">${esc(i.filename)}</div></td>
      <td>${esc(i.supplier_name || "—")}</td>
      <td>${esc(i.supplier_nit || "—")}</td>
      <td>${fmtDate(i.issue_date)}</td>
      <td class="num">${fmtMoney(i.total)}</td>
      <td>${chip(i.status)}${i.issue_count ? `<span class="count">${i.issue_count} alerta(s)</span>` : ""}</td>
    </tr>`).join("");
}

async function uploadFiles(files) {
  const pdfs = [...files].filter((f) => f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf"));
  const status = $("#upload-status");
  for (const [n, f] of pdfs.entries()) {
    status.textContent = `Procesando ${n + 1}/${pdfs.length}: ${f.name}…`;
    const body = new FormData(); body.append("file", f);
    try { await api("/api/invoices", { method: "POST", body }); }
    catch (err) { status.textContent = `Error en ${f.name}: ${err.message}`; return; }
  }
  status.textContent = pdfs.length ? `${pdfs.length} factura(s) procesada(s)` : "Solo se aceptan archivos PDF";
  loadList();
}

async function exportFile(format) {
  const res = await api(`/api/invoices/export?format=${format}`);
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: `facturas-aprobadas.${format}` });
  a.click(); URL.revokeObjectURL(url);
}

// ---------- Review ----------
function confColor(c) { return c >= 0.9 ? "#1d8a5a" : c >= 0.8 ? "#5aa06b" : c >= 0.5 ? "#d99a1e" : "#c94040"; }

function renderReview(inv) {
  current = inv;
  $("#review-title").textContent = `Factura ${inv.invoice_number || "sin número"}`;
  $("#review-sub").textContent = `${inv.supplier_name || "Proveedor desconocido"} · ${inv.filename}`;
  $("#review-status").innerHTML = chip(inv.status);
  const flagged = new Map(inv.review_reasons.filter((r) => r.field).map((r) => [r.field, r.severity]));
  const readOnly = inv.status === "approved";
  $("#fields").innerHTML = inv.fields.map((f) => {
    const pct = Math.round(f.confidence * 100);
    const value = AMOUNT_FIELDS.includes(f.name) && f.value ? Number(f.value).toFixed(2) : f.value ?? "";
    const cls = flagged.get(f.name) === "error" ? "error" : flagged.has(f.name) ? "flag" : "";
    return `<div class="field ${cls}">
      <label for="f-${f.name}">${esc(f.label)}
        <span class="conf"><span class="src ${f.source}">${SOURCE_LABEL[f.source]}</span>
          <span class="bar"><i style="width:${pct}%;background:${confColor(f.confidence)}"></i></span>${pct}%</span>
      </label>
      <input id="f-${f.name}" name="${f.name}" value="${esc(value)}" ${readOnly ? "disabled" : ""}
        placeholder="${f.name === "issue_date" ? "AAAA-MM-DD o DD/MM/AAAA" : f.name === "supplier_nit" ? "900123456-7" : ""}">
    </div>`;
  }).join("");
  $("#issues").innerHTML = inv.review_reasons.length
    ? inv.review_reasons.map((r) => `<li class="${r.severity}">${esc(r.message)}</li>`).join("")
    : `<li class="ok">Sin alertas: los datos cuadran.</li>`;
  $("#meta").innerHTML = `<h2>Detalles</h2><dl>
    <dt>Archivo</dt><dd><a href="#" id="open-pdf">${esc(inv.filename)}</a></dd>
    <dt>Procesamiento</dt><dd>${inv.processing_ms ?? "—"} ms</dd>
    <dt>Aprobada</dt><dd>${inv.approved_at ? new Date(inv.approved_at).toLocaleString("es-CO") : "Pendiente"}</dd>
    ${inv.approved_by ? `<dt>Aprobada por</dt><dd>${esc(inv.approved_by)}</dd>` : ""}</dl>`;
  $("#raw-text").textContent = inv.raw_text;
  $("#save-btn").hidden = $("#approve-btn").hidden = readOnly;
  $("#open-pdf").onclick = openPdf;
}

function showMsg(text, ok) { const m = $("#review-msg"); m.textContent = text; m.className = `msg ${ok ? "ok" : "err"}`; m.hidden = false; }

function changedFields() {
  const out = {};
  for (const f of current.fields) {
    const input = $(`#f-${f.name}`);
    const orig = AMOUNT_FIELDS.includes(f.name) && f.value ? Number(f.value).toFixed(2) : f.value ?? "";
    if (input.value !== orig) out[f.name] = input.value;
  }
  return out;
}

async function saveFields() {
  const fields = changedFields();
  if (!Object.keys(fields).length) return true;
  try {
    const res = await api(`/api/invoices/${current.id}/fields`, { method: "PATCH", json: { fields } });
    renderReview(await res.json()); showMsg("Cambios guardados y revalidados.", true); return true;
  } catch (err) { showMsg(err.message, false); return false; }
}

async function approve(force = false) {
  if (!(await saveFields())) return;
  try {
    const res = await api(`/api/invoices/${current.id}/approve`, { method: "POST", json: { force } });
    renderReview(await res.json()); showMsg("Factura aprobada.", true);
  } catch (err) {
    if (err.status === 409 && me?.role === "owner" && !force
        && confirm("La factura tiene errores de validación. ¿Aprobar de todas formas?")) return approve(true);
    showMsg(err.status === 409 ? "Corrige los errores de validación antes de aprobar." : err.message, false);
  }
}

async function openPdf(e) {
  e.preventDefault();
  const res = await api(`/api/invoices/${current.id}/file`);
  window.open(URL.createObjectURL(await res.blob()), "_blank");
}

// ---------- Router ----------
async function route() {
  if (!token) { $("#auth-view").hidden = false; $("#app-view").hidden = true; return; }
  try { if (!me) me = await (await api("/api/me")).json(); } catch { return; }
  $("#auth-view").hidden = true; $("#app-view").hidden = false;
  $("#org-name").textContent = me.organization_name;
  $("#user-email").textContent = `${me.email} · ${me.role === "owner" ? "Propietario" : "Miembro"}`;
  const m = location.hash.match(/^#\/factura\/(.+)$/);
  $("#list-view").hidden = !!m; $("#review-view").hidden = !m; $("#review-msg").hidden = true;
  if (m) renderReview(await (await api(`/api/invoices/${m[1]}`)).json());
  else loadList();
}

function init() {
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => setAuthMode(t.dataset.mode)));
  $("#auth-form").addEventListener("submit", submitAuth);
  $("#logout").addEventListener("click", logout);
  $("#filters").addEventListener("click", (e) => {
    const b = e.target.closest(".chip-filter"); if (!b) return;
    filter = b.dataset.status;
    document.querySelectorAll(".chip-filter").forEach((x) => x.classList.toggle("active", x === b));
    loadList();
  });
  $("#invoice-rows").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-id]"); if (tr) location.hash = `#/factura/${tr.dataset.id}`;
  });
  document.querySelectorAll("[data-export]").forEach((b) => b.addEventListener("click", () => exportFile(b.dataset.export)));
  const dz = $("#dropzone");
  $("#file-input").addEventListener("change", (e) => uploadFiles(e.target.files));
  ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
  dz.addEventListener("drop", (e) => uploadFiles(e.dataTransfer.files));
  $("#fields-form").addEventListener("submit", (e) => { e.preventDefault(); saveFields(); });
  $("#approve-btn").addEventListener("click", () => approve());
  window.addEventListener("hashchange", route);
  route();
}
init();
