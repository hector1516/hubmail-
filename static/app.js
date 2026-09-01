const state = {
  token: localStorage.getItem("hubmail_token"),
  user: null,
  accounts: [],
  currentAccountId: null,
  folders: [],
  folderDelimiter: "",
  expandedFolders: {},
  foldersByAccount: {},
  expandedByAccount: {},
  currentFolder: "INBOX",
  messages: [],
  total: 0,
  lastSync: null,
  page: 1,
  q: "",
  unreadOnly: false,
  currentMsgId: null,
  currentMsg: null,
  unified: false,
  theme: localStorage.getItem("hubmail_theme") || "light",
  composeAttachments: [],
  selected: new Set(),
  notified: new Set(),
  notifiedSeeded: false,
  signature_html: "",
  unreadByAccount: {},
  collapsedAccounts: new Set(),
  userColors: {},
  paneWidths: { sidebar: 270, list: 380 },
  hasMore: true,
  loadingMore: false,
  splashPhrases: [],
};

let dragData = null;

const ACC_FALLBACK_COLORS = [
  "#2a6fd6", "#8e44ad", "#d63031", "#0984e3", "#00b894", "#e17055",
  "#e84393", "#6c5ce7", "#00cec9", "#e67e22", "#d35400", "#16a085",
];

function accColor(acc) {
  if (acc && state.userColors && state.userColors[acc.id]) return state.userColors[acc.id];
  if (acc && acc.color) return acc.color;
  const id = acc ? acc.id : 0;
  return ACC_FALLBACK_COLORS[Math.abs(id) % ACC_FALLBACK_COLORS.length];
}

async function loadPrefs() {
  const key = state.user ? `hubmail_panes_${state.user.id}` : null;
  if (key) {
    try {
      const p = JSON.parse(localStorage.getItem(key) || "{}");
      state.paneWidths = { sidebar: p.sidebar || 270, list: p.list || 380 };
    } catch (e) {}
  }
  try {
    const d = await api("/settings/colors");
    state.userColors = d.colors || {};
  } catch (e) {}
}

function savePaneWidths() {
  const key = state.user ? `hubmail_panes_${state.user.id}` : null;
  if (!key) return;
  try {
    localStorage.setItem(key, JSON.stringify(state.paneWidths));
  } catch (e) {}
}

/* ============================================================ tema */
function applyTheme(t) {
  state.theme = t === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = state.theme;
  try { localStorage.setItem("hubmail_theme", state.theme); } catch (e) {}
  const btn = document.getElementById("btn-theme");
  if (btn) btn.textContent = state.theme === "dark" ? "☀️" : "🌙";
  const da = document.getElementById("da-theme");
  if (da) da.innerHTML = state.theme === "dark" ? "☀️ Tema claro" : "🌙 Tema oscuro";
}

function toggleTheme() {
  applyTheme(state.theme === "dark" ? "light" : "dark");
}

/* ============================================================ helpers UI */
function avatarFor(name, email) {
  const s = String(name || email || "?").trim();
  const letter = (s[0] || "?").toUpperCase();
  let h = 7;
  const e = String(email || name || "x");
  for (let i = 0; i < e.length; i++) h = (h * 31 + e.charCodeAt(i)) >>> 0;
  const pal = ["#2a6fd6", "#8e44ad", "#d63031", "#0984e3", "#00b894", "#e17055", "#e84393", "#6c5ce7", "#00cec9", "#e67e22"];
  return `<span class="avatar" style="background:${pal[h % pal.length]}">${esc(letter)}</span>`;
}

function cardDate(d) {
  if (!d) return "";
  const dt = new Date(String(d).replace(" ", "T"));
  if (isNaN(dt)) return d;
  const now = new Date();
  if (dt.toDateString() === now.toDateString()) {
    return dt.toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" });
  }
  return dt.toLocaleDateString("es-MX", { day: "2-digit", month: "2-digit", year: "2-digit" });
}

function msgCtx(m) {
  if (!m) return { accountId: state.currentAccountId, folder: state.currentFolder };
  return { accountId: m.account_id || state.currentAccountId, folder: m.folder || state.currentFolder };
}

function openDrawer() {
  const d = document.getElementById("sidebar");
  if (d) d.classList.add("open");
  const o = document.getElementById("drawer-overlay");
  if (o) o.classList.add("show");
}

function closeDrawer() {
  const d = document.getElementById("sidebar");
  if (d) d.classList.remove("open");
  const o = document.getElementById("drawer-overlay");
  if (o) o.classList.remove("show");
}

function openSidebar() {
  openDrawer();
}

function closeSidebar() {
  closeDrawer();
}

function toggleSidebar() {
  const d = document.getElementById("sidebar");
  const btn = document.getElementById("sidebar-toggle");
  if (d && d.classList.contains("collapsed")) {
    d.classList.remove("collapsed");
    if (btn) btn.textContent = "◀";
  } else {
    d.classList.add("collapsed");
    if (btn) btn.textContent = "▶";
  }
}

function focusSearch() {
  const el = document.getElementById("search-box");
  if (el) { el.focus(); el.scrollIntoView({ block: "center", behavior: "smooth" }); }
}

/* ============================================================ swipe */
function attachSwipe(el, onDelete, onToggleRead) {
  const inner = el.querySelector(".msg-card-inner");
  const sb = el.querySelector(".swipe-bg");
  const LIMIT = 84;
  let startX = 0, startY = 0, dx = 0, active = false, horiz = false;
  const setDx = v => {
    dx = v;
    if (inner) inner.style.transform = `translateX(${v}px)`;
    if (sb) sb.style.opacity = Math.min(1, Math.abs(v) / 60);
  };
  const reset = () => {
    setDx(0);
    if (sb) { sb.classList.remove("show-del", "show-read"); sb.style.opacity = ""; }
  };
  el.addEventListener("touchstart", e => {
    if (e.touches.length !== 1) return;
    startX = e.touches[0].clientX;
    startY = e.touches[0].clientY;
    active = true;
    horiz = false;
    if (inner) inner.style.transition = "none";
  }, { passive: true });
  el.addEventListener("touchmove", e => {
    if (!active) return;
    const cx = e.touches[0].clientX;
    const cy = e.touches[0].clientY;
    const del = cx - startX;
    const dely = cy - startY;
    if (!horiz) {
      if (Math.abs(del) < 8 && Math.abs(dely) < 8) return;
      horiz = Math.abs(del) > Math.abs(dely);
      if (!horiz) return;
    }
    e.preventDefault();
    const v = Math.max(-LIMIT, Math.min(LIMIT, del));
    setDx(v);
    if (sb) {
      sb.classList.toggle("show-del", v < -30);
      sb.classList.toggle("show-read", v > 30);
    }
  }, { passive: false });
  const end = () => {
    if (!active) return;
    active = false;
    if (inner) inner.style.transition = "";
    if (dx < -60) {
      setDx(-140);
      el._swiped = true;
      setTimeout(() => { onDelete && onDelete(); }, 140);
    } else if (dx > 60) {
      setDx(140);
      el._swiped = true;
      setTimeout(() => { onToggleRead && onToggleRead(); }, 140);
    } else {
      reset();
    }
  };
  el.addEventListener("touchend", end);
  el.addEventListener("touchcancel", end);
}

async function quickCardAction(el, action) {
  const id = el.dataset.id;
  const accId = parseInt(el.dataset.acc, 10) || state.currentAccountId;
  const folder = el.dataset.folder || state.currentFolder;
  try {
    if (action === "delete") {
      await api(`/accounts/${accId}/messages/${encodeURIComponent(id)}?folder=${encodeURIComponent(folder)}&action=delete`, { method: "PATCH" });
      toast("Mensaje eliminado", "ok");
    } else {
      const msg = state.messages.find(x => x.id === id);
      const cur = msg ? msg.unread : true;
      await api(`/accounts/${accId}/messages/${encodeURIComponent(id)}?folder=${encodeURIComponent(folder)}&action=${cur ? "read" : "unread"}`, { method: "PATCH" });
      if (msg) msg.unread = !cur;
      toast(cur ? "Marcado como leído" : "Marcado como no leído", "ok");
    }
    el.remove();
    loadUnreadCounts().catch(() => {});
  } catch (e) {
    toast(e.message, "error");
  }
}

function initGutter(gutterId, targetId, which) {
  const gutter = document.getElementById(gutterId);
  if (!gutter) return;
  gutter.addEventListener("mousedown", e => {
    e.preventDefault();
    document.body.classList.add("resizing");
    const startX = e.clientX;
    const startW = document.getElementById(targetId).offsetWidth;
    const onMove = ev => {
      const dx = ev.clientX - startX;
      let w = startW + dx;
      if (which === "sidebar") w = Math.max(190, Math.min(420, w));
      else w = Math.max(280, Math.min(720, w));
      document.getElementById(targetId).style.width = w + "px";
      state.paneWidths[which] = w;
    };
    const onUp = () => {
      document.body.classList.remove("resizing");
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      savePaneWidths();
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  });
}

const app = document.getElementById("app");
const modalRoot = document.getElementById("modal-root");
const toastRoot = document.getElementById("toast-root");

let _phraseInterval = null;

function _rotatePhrase() {
  const p = document.getElementById("loading-phrase");
  if (p && state.splashPhrases.length) {
    p.style.opacity = "0";
    setTimeout(() => {
      p.textContent = state.splashPhrases[Math.floor(Math.random() * state.splashPhrases.length)];
      p.style.opacity = "1";
    }, 200);
  }
}

function showLoading(text = "Cargando…") {
  const o = document.getElementById("loading-overlay");
  const t = document.getElementById("loading-text");
  if (t) t.textContent = text;
  if (o) o.classList.remove("hidden");
  _rotatePhrase();
  clearInterval(_phraseInterval);
  _phraseInterval = setInterval(_rotatePhrase, 3500);
}

function hideLoading() {
  clearInterval(_phraseInterval);
  _phraseInterval = null;
  const o = document.getElementById("loading-overlay");
  if (o) o.classList.add("hidden");
}

function hideSplash() {
  const s = document.getElementById("splash");
  if (s) s.style.display = "none";
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function toast(msg, type = "") {
  const t = document.createElement("div");
  t.className = "toast " + type;
  t.textContent = msg;
  toastRoot.appendChild(t);
  setTimeout(() => t.remove(), 4000);
}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers["Authorization"] = "Bearer " + state.token;
  const res = await fetch("/api" + path, { ...opts, headers });
  if (res.status === 401) {
    logout();
    throw new Error("Sesión expirada");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Error en el servidor");
  return data;
}

function openModal(html, extraClass = "") {
  modalRoot.innerHTML = `<div class="modal-backdrop"><div class="modal ${extraClass}">${html}</div></div>`;
  modalRoot.querySelector(".modal-backdrop").addEventListener("click", e => {
    if (e.target === e.currentTarget) closeModal();
  });
}

function closeModal() {
  modalRoot.innerHTML = "";
}

async function openAdminActivity() {
  try {
    const data = await api("/api/admin/activity");
    renderActivityModal(data, {});
  } catch (e) {
    toast(e.message, "error");
  }
}

function renderActivityModal(data, sel) {
  const accSel = `<option value="">Todas las cuentas</option>` +
    (data.accounts || []).map(a =>
      `<option value="${a.id}" ${sel.account_id == a.id ? "selected" : ""}>${esc(a.email)}</option>`).join("");
  const userSel = `<option value="">Todos los usuarios</option>` +
    (data.users || []).map(u =>
      `<option value="${esc(u)}" ${sel.user_filter === u ? "selected" : ""}>${esc(u)}</option>`).join("");
  const items = (data.items || []).map(it => `
    <tr>
      <td>${esc(it.account_id)}</td>
      <td>${esc(it.user)}</td>
      <td class="act-action">${esc(it.action)}</td>
      <td>${esc(it.details)}</td>
      <td class="act-date">${fmtDt(it.created_at)}</td>
    </tr>`).join("") || '<tr><td colspan="5" class="act-empty">Sin actividad registrada</td></tr>';
  openModal(`
    <div class="act-head">
      <h3>📋 Log de actividad de cuentas</h3>
      <button class="icon-btn btn-sm" onclick="closeModal()">✕</button>
    </div>
    <div class="act-filters">
      <select id="act-account" class="field-select">${accSel}</select>
      <select id="act-user" class="field-select">${userSel}</select>
      <button class="btn btn-ghost btn-sm" id="act-refresh">Refrescar</button>
    </div>
    <div class="act-table-wrap">
      <table class="act-table">
        <thead><tr><th>#</th><th>Usuario</th><th>Acción</th><th>Detalle</th><th>Fecha</th></tr></thead>
        <tbody>${items}</tbody>
      </table>
    </div>`, "modal-lg");
  document.getElementById("act-refresh").onclick = async () => {
    const accountId = document.getElementById("act-account").value;
    const userFilter = document.getElementById("act-user").value;
    const qs = new URLSearchParams();
    if (accountId) qs.set("account_id", accountId);
    if (userFilter) qs.set("user_filter", userFilter);
    try {
      const data = await api(`/api/admin/activity?${qs.toString()}`);
      renderActivityModal(data, { account_id: accountId, user_filter: userFilter });
    } catch (e) {
      toast(e.message, "error");
    }
  };
  document.getElementById("act-account").onchange = () => document.getElementById("act-refresh").click();
  document.getElementById("act-user").onchange = () => document.getElementById("act-refresh").click();
}

let syncStatusTimer = null;

async function openAdminSyncStatus() {
  if (syncStatusTimer) clearInterval(syncStatusTimer);
  openModal(`
    <div class="act-head">
      <h3>📊 Estado de sincronización de cuentas</h3>
      <button class="icon-btn btn-sm" onclick="closeModal()">✕</button>
    </div>
    <div class="act-filters">
      <span class="sync-hint">Se actualiza solo cada 3 segundos. Duración = tiempo del último ciclo de esa cuenta.</span>
    </div>
    <div class="act-table-wrap">
      <table class="act-table">
        <thead><tr><th>Cuenta</th><th>Estado</th><th>Carpeta actual</th><th>Duración</th><th>Último sync</th><th>Progreso</th></tr></thead>
        <tbody id="sync-status-list"><tr><td colspan="6" class="act-empty">Cargando…</td></tr></tbody>
      </table>
    </div>`, "modal-lg");
  await renderSyncStatus();
  syncStatusTimer = setInterval(async () => {
    if (!document.getElementById("sync-status-list")) {
      clearInterval(syncStatusTimer);
      syncStatusTimer = null;
      return;
    }
    await renderSyncStatus();
  }, 3000);
}

async function renderSyncStatus() {
  const list = document.getElementById("sync-status-list");
  if (!list) return;
  try {
    const data = await api("/admin/sync-status");
    const rows = (data.accounts || []).map(a => {
      const status = a.status || "idle";
      const pct = a.folder_count ? Math.round((a.folder_index / a.folder_count) * 100) : 0;
      const barCls = status === "syncing" ? "progress-indet"
        : status === "error" ? "progress-error"
        : status === "ok" ? "progress-ok" : "progress-idle";
      const barWidth = (status === "syncing" && a.folder_count) ? Math.max(6, pct) + "%" : "100%";
      const statusText = status === "syncing" ? `Sincronizando ${pct}%`
        : status === "error" ? `Error${a.error ? ": " + a.error : ""}`
        : status === "ok" ? "OK" : "En espera";
      return `<tr>
        <td>${esc(a.email)}</td>
        <td><span class="st-${status}">${esc(statusText)}</span></td>
        <td>${esc(a.current_folder || "—")}</td>
        <td>${a.duration != null ? esc(a.duration) + " s" : "—"}</td>
        <td class="act-date">${esc(a.last_sync || "—")}</td>
        <td><div class="progress-bar ${barCls}"><div style="width:${barWidth}"></div></div></td>
      </tr>`;
    }).join("") || '<tr><td colspan="6" class="act-empty">Sin cuentas</td></tr>';
    list.innerHTML = rows;
  } catch (e) {
    if (document.getElementById("sync-status-list")) {
      list.innerHTML = `<tr><td colspan="6" class="act-empty">Error: ${esc(e.message)}</td></tr>`;
    }
  }
}

async function openAdminErrors() {
  try {
    const data = await api("/admin/sync-errors");
    const items = (data.items || []).map(it => `
      <tr>
        <td>${esc(it.account_id)}</td>
        <td>${esc(it.folder || "—")}</td>
        <td class="err-text">${esc(it.error)}</td>
        <td class="act-date">${esc(it.created_at || "")}</td>
      </tr>`).join("") || '<tr><td colspan="4" class="act-empty">Sin errores registrados</td></tr>';
    openModal(`
      <div class="act-head">
        <h3>⚠️ Errores de sincronización</h3>
        <button class="icon-btn btn-sm" onclick="closeModal()">✕</button>
      </div>
      <div class="act-filters">
        <button class="btn btn-ghost btn-sm" id="err-refresh">Refrescar</button>
      </div>
      <div class="act-table-wrap">
        <table class="act-table">
          <thead><tr><th>Cuenta</th><th>Carpeta</th><th>Error</th><th>Fecha</th></tr></thead>
          <tbody>${items}</tbody>
        </table>
      </div>`, "modal-lg");
    document.getElementById("err-refresh").onclick = () => openAdminErrors();
  } catch (e) {
    toast(e.message, "error");
  }
}

async function applyWallpaper() {
  try {
    const res = await fetch("/api/wallpaper");
    const data = await res.json();
    if (data.url) {
      const wall = `url("${data.url}")`;
      document.body.style.backgroundImage = wall;
      document.body.style.backgroundSize = "cover";
      document.body.style.backgroundPosition = "center";
      document.body.style.backgroundAttachment = window.innerWidth > 900 ? "fixed" : "scroll";
      const wrap = document.querySelector(".login-wrap");
      if (wrap) {
        wrap.style.setProperty("--wallpaper", wall);
        wrap.setAttribute("data-bg", "1");
      }
    }
  } catch (e) {}
}

/* ============================================================ login */
function renderLogin() {
  app.innerHTML = `
    <div class="login-wrap">
      <div class="login-bg"></div>
      <div class="login-overlay"></div>
      <div class="login-card">
        <div class="login-logo">
          <img src="/engrane.png" alt="ECCSA" class="login-logo-img">
          <div class="login-logo-text">
            <div class="login-brand">ECCSA</div>
            <div class="login-brand-sub">Correo corporativo</div>
          </div>
        </div>
        <h1>Bienvenido</h1>
        <div class="sub">Inicia sesión en tu correo</div>
        <div class="field"><label>Correo</label><input id="lg-email" type="email" placeholder="usuario@ecc-sa.com.mx" autocomplete="username"></div>
        <div class="field"><label>Contraseña</label><input id="lg-pass" type="password" placeholder="••••••••" autocomplete="current-password"></div>
        <button class="btn btn-primary" id="lg-btn" style="width:100%;padding:11px">Iniciar sesión</button>
        <div class="login-foot">⚡ ECCSA Automation - Soluciones en Automatización y Control © 2026 ⚙️ · v0.1.0</div>
      </div>
    </div>`;
  applyWallpaper();
  const doLogin = async () => {
    const email = document.getElementById("lg-email").value.trim();
    const password = document.getElementById("lg-pass").value;
    if (!email || !password) return toast("Ingresa correo y contraseña", "error");
    showLoading("Iniciando sesión…");
    try {
      const data = await api("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
      state.token = data.token;
      localStorage.setItem("hubmail_token", data.token);
      state.user = await api("/auth/me");
      await boot();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      hideLoading();
    }
  };
  document.getElementById("lg-btn").onclick = doLogin;
  document.getElementById("lg-pass").addEventListener("keydown", e => { if (e.key === "Enter") doLogin(); });
}

function logout() {
  if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null; }
  state.token = null;
  state.notified = new Set();
  state.notifiedSeeded = false;
  const stack = document.getElementById("notif-stack");
  if (stack) stack.innerHTML = "";
  localStorage.removeItem("hubmail_token");
  renderLogin();
}

/* ============================================================ shell */

const WELCOME_LINES = [
  (n, u) => `Tienes ${u} correo${u === 1 ? "" : "s"} sin leer, ${n}. Tu bandeja lleva contando los minutos… y los no leídos. 📬`,
  (n, u) => `${n}, esos ${u} correo${u === 1 ? "" : "s"} no se van a leer solos. Bueno, podrían… pero hoy les toca a ti. 😄`,
  (n, u) => `Bienvenido de vuelta, ${n}. El café ya está listo y tu bandeja también: ${u} pendiente${u === 1 ? "" : "s"} esperando. ☕`,
  (n, u) => `¡Hola ${n}! A tu bandeja le urgen vacaciones, pero por hoy ${u} correo${u === 1 ? "" : "s"} te recuerdan quién manda. 😅`,
  (n, u) => `${n}, tu INBOX amaneció con hambre: ${u} correo${u === 1 ? "" : "s"} para desayunar. 🍳`,
  (n, u) => `Nadie dijo que ser ${n} fuera fácil: te esperan ${u} correo${u === 1 ? "" : "s"} sin leer y una taza de café con tu nombre. 🏆`,
  (n, u) => `Reporte matutino, ${n}: ${u} mensaje${u === 1 ? "" : "s"} sin abrir. La bandeja confía plenamente en ti (aunque ya tiene dudas). 🤔`,
  (n, u) => `¡Saludos, ${n}! Aquí tu resumen: ${u} correo${u === 1 ? "" : "s"} jugando a las escondidas. Adivina quién tiene que encontrarlos… 👀`,
  (n, u) => `${n}, esos ${u} correo${u === 1 ? "" : "s"} llevan rato gritando “léeme”. Hoy sí les haces caso, ¿no? 😜`,
  (n, u) => `Bienvenido, ${n}. Estadística del día: ${u} correo${u === 1 ? "" : "s"} sin leer y ${u === 0 ? "una bandeja muy relajada 😌" : "un dedo muy ocupado 👆"}`,
  (n, u) => `Hola ${n}, tu bandeja tiene ${u} pendiente${u === 1 ? "" : "s"} y cero paciencia. Manos a la obra. 🚀`,
  (n, u) => `${n}, los ${u} correo${u === 1 ? "" : "s"} sin leer te mandan saludos desde tu carpeta de entrada. Eso es muy de ellos. 📥`,
  (n, u) => `¡Ahí está ${n}! Mientras no mirabas, llegaron ${u} correo${u === 1 ? "" : "s"} más. La bandeja nunca duerme (tú tampoco, ¿verdad?). 🌙`,
  (n, u) => `Bienvenido, ${n}. Tu resumen de pendientes es corto y claro: ${u} correo${u === 1 ? "" : "s"}. Suerte (la vas a necesitar). 🍀`,
  (n, u) => `${n}, el correo no se responde solo… aunque a veces desearíamos que sí. ${u} pendiente${u === 1 ? "" : "s"} te esperan. 💪`,
];

function welcomeLine(name, unread) {
  const lines = WELCOME_LINES;
  return lines[Math.floor(Math.random() * lines.length)](name, unread);
}

function fmtDt(dt) {
  if (!dt) return "";
  const d = new Date(dt);
  if (isNaN(d)) return "";
  return d.toLocaleString("es-MX", {
    day: "numeric", month: "long", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

async function maybeShowWelcome() {
  try {
    const today = new Date().toISOString().slice(0, 10);
    const key = `hubmail_welcome_${state.user.id}_${today}`;
    if (localStorage.getItem(key)) return;
    localStorage.setItem(key, "1");
    await openWelcome();
  } catch (e) {}
}

async function openWelcome() {
  try {
    const data = await api("/welcome");
    showWelcome(data);
  } catch (e) {
    toast(e.message, "error");
  }
}

function showWelcome(d) {
  const firstName = (state.user.name || "amigo").split(" ")[0];
  const total = d.total_unread || 0;
  const greeting = d.first_login
    ? `¡Bienvenido a bordo, ${firstName}! 🎉`
    : `¡Bienvenido de vuelta, ${firstName}! 👋`;
  const foldersHtml = (d.folders || []).map(f =>
    `<span class="wm-folder"><span class="wm-folder-name">${esc(f.folder)}</span><b>${f.count}</b></span>`
  ).join("");
  const previewHtml = (d.preview || []).map(m =>
    `<div class="wm-mail">
      <div class="wm-mail-left">
        <div class="wm-mail-from">${esc(m.from_name || m.from_email || "(remitente desconocido)")}</div>
        <div class="wm-mail-subject">${esc(m.subject)}</div>
      </div>
      <div class="wm-mail-right">
        <span class="wm-folder-tag">${esc(m.folder)}</span>
        <span class="wm-mail-date">${fmtDt(m.date)}</span>
      </div>
    </div>`).join("");

  const resumeHtml = d.last_login
    ? `<div class="wm-resume">Este es tu resumen desde <b>${fmtDt(d.last_login)}</b>:</div>`
    : `<div class="wm-resume">Este es tu resumen de pendientes al día de hoy:</div>`;

  const activityHtml = (d.activity || []).map(a =>
    `<div class="activity-item">
      <span class="activity-user">${esc(a.user)}</span>
      <span class="activity-text">${esc(a.details)}</span>
      <span class="activity-account">${esc(a.account)}</span>
      <span class="activity-time">${fmtDt(a.created_at)}</span>
    </div>`).join("");

  const bodyHtml = total === 0
    ? `<div class="wm-clear">🎉 ¡Cero pendientes, ${firstName}! Tu bandeja está tan en paz que casi se oyen mariposas. Disfrútalo mientras dure. 🦋</div>`
    : `${resumeHtml}
      <div class="wm-stats">
        <div class="wm-stat main"><div class="wm-num">${total}</div><div>correos sin leer</div></div>
        <div class="wm-stat"><div class="wm-num">${(d.folders || []).length}</div><div>carpetas</div></div>
        <div class="wm-stat"><div class="wm-num">${(d.preview || []).length}</div><div>recientes</div></div>
      </div>
      ${foldersHtml ? `<div class="wm-folders">${foldersHtml}</div>` : ""}
      ${previewHtml ? `<div class="wm-section">Recientes sin leer:</div><div class="wm-preview">${previewHtml}</div>` : ""}
      ${activityHtml ? `<div class="wm-section">Actividad reciente en tus cuentas:</div><div class="wm-preview wm-activity">${activityHtml}</div>` : ""}`;

  const noteHtml = `<div class="wm-note">🧹 Nota del sistema: Spam, Basura y Papelera se autolimpian cada día, como buenos ciudadanos. Ahí solo viven los últimos 10 correos y nada mayor a una semana. La limpieza es cortesía de HUBMail; el resto es tu problema. 😌</div>`;

  const SPAM_QUOTES = [
    "Cada príncipe nigeriano fue interceptado antes de su coronación. 👑",
    "La IA de ECCSA lee el spam para que tú no tengas que hacerlo. Te salva la vista (y el seso). 🧠",
    "Adelgazó tu bandeja y ni cuenta te diste. Es como un régimen, pero en tu correo. 🏋️",
    "Los herederos millonarios y sus parientes enfermos ya no llegan ni al portón. 🚪",
    "Es tan buena que el spam ya casi ni te saluda. ¿La sientes fría? Es profesional. 😎",
    "El spam no desapareció: solo aprendió a tener miedo. 🫣",
  ];
  const spamHtml = `<div class="wm-spam">
    <div class="wm-spam-head">
      <div class="wm-spam-logo">🛡️</div>
      <div>
        <div class="wm-spam-title">ECCSA Anti-Spam</div>
        <div class="wm-spam-sub">Inteligencia Artificial en defensa de tu bandeja</div>
      </div>
    </div>
    <div class="wm-spam-stats">
      <div class="wm-spam-stat"><div class="wm-num">${esc(d.spam_blocked_7d ?? 0)}</div><div>neutralizados en 7 días</div></div>
      <div class="wm-spam-stat"><div class="wm-num">${esc(d.spam_total ?? 0)}</div><div>en cuarentena</div></div>
    </div>
    <div class="wm-spam-quote">${SPAM_QUOTES[Math.floor(Math.random() * SPAM_QUOTES.length)]}</div>
  </div>`;

  openModal(`
    <div class="welcome-modal">
      <div class="wm-hero">${greeting}</div>
      <div class="wm-slogan">${welcomeLine(firstName, total)}</div>
      ${bodyHtml}
      ${spamHtml}
      ${noteHtml}
      <div class="actions">
        <button class="btn-primary btn" id="wm-close">${total ? "¡A trabajar! 💪" : "¡Perfecto! ✅"}</button>
      </div>
    </div>`, "modal-wide");
  document.getElementById("wm-close").onclick = closeModal;
}

/* ============================================================ shell */
async function boot() {
  try {
    await loadPrefs();
    await loadAccounts();
    api("/contacts/collect", { method: "POST" }).catch(() => {});
    try {
      const s = await api("/settings");
      state.signature_html = s.signature_html || "";
    } catch (e) {}
    if (!state.accounts.length) {
      renderShell();
      toast("No tienes cuentas de correo. Agrégalas en Configuración.");
      openAccountsModal();
      return;
    }
    const def = state.accounts.find(a => a.is_default) || state.accounts[0];
    state.currentAccountId = def.id;
    const fa = state.foldersByAccount[def.id] || { folders: [], delimiter: "/" };
    state.folders = fa.folders;
    state.folderDelimiter = fa.delimiter;
    state.expandedFolders = state.expandedByAccount[def.id] || {};
    state.currentFolder = "INBOX";
    state.unified = true;
    renderShell();
    Promise.race([
      loadMessages().then(() => renderContent()),
      new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), 15000)),
    ]).catch(() => {
      toast("La carga de mensajes está lenta. Intenta refrescar.", "error");
    });
    startNotifications();
    startFolderRefresh();
    initPushNotifications();
    maybeShowWelcome();
  } catch (e) {
    toast(e.message, "error");
  }
}

async function loadAccounts() {
  showLoading("Cargando cuentas y carpetas…");
  try {
    state.accounts = await api("/accounts");
    state.foldersByAccount = {};
    state.expandedByAccount = {};
    await Promise.all(state.accounts.map(async acc => {
      try {
        const res = await api(`/accounts/${acc.id}/folders`);
        const folders = res.folders || [];
        const delimiter = res.delimiter || "/";
        state.foldersByAccount[acc.id] = { folders, delimiter };
        state.expandedByAccount[acc.id] = autoExpand(folders, delimiter);
        if (state.currentAccountId === acc.id) {
          state.folders = folders;
          state.folderDelimiter = delimiter;
          state.expandedFolders = state.expandedByAccount[acc.id];
        }
      } catch (e) {
        state.foldersByAccount[acc.id] = { folders: [], delimiter: "/" };
        state.expandedByAccount[acc.id] = {};
      }
    }));
    await loadUnreadCounts();
  } finally {
    hideLoading();
  }
}

async function loadUnreadCounts() {
  state.unreadByAccount = {};
  await Promise.all(state.accounts.map(async acc => {
    try {
      const u = await api(`/accounts/${acc.id}/unread`);
      state.unreadByAccount[acc.id] = u;
    } catch (e) {
      state.unreadByAccount[acc.id] = { folders: [], total: 0 };
    }
  }));
  updateUnreadBadges();
}

function updateUnreadBadges() {
  document.querySelectorAll("[data-unread]").forEach(el => {
    const [accId, folder] = el.dataset.unread.split("|");
    const u = state.unreadByAccount[accId];
    const n = u ? (u.folders.find(f => f.folder === folder)?.count || 0) : 0;
    el.textContent = n ? (n > 999 ? "999+" : n) : "";
    el.style.display = n ? "" : "none";
  });
  document.querySelectorAll("[data-accunread]").forEach(el => {
    const accId = el.dataset.accunread;
    const u = state.unreadByAccount[accId];
    const n = u ? (u.total || 0) : 0;
    el.textContent = n ? (n > 999 ? "999+" : n) : "";
    el.style.display = n ? "" : "none";
  });
  const ub = document.getElementById("unified-badge");
  if (ub) {
    const n = state.accounts.reduce((a, acc) => a + ((state.unreadByAccount[acc.id] || {}).total || 0), 0);
    ub.textContent = n ? (n > 999 ? "999+" : n) : "";
    ub.style.display = n ? "" : "none";
  }
}

async function loadFolders() {
  if (!state.currentAccountId) return;
  const res = await api(`/accounts/${state.currentAccountId}/folders`);
  state.folders = res.folders || [];
  state.folderDelimiter = res.delimiter || "";
  state.foldersByAccount[state.currentAccountId] = { folders: state.folders, delimiter: state.folderDelimiter };
  state.expandedFolders = autoExpand(state.folders, state.folderDelimiter);
  state.expandedByAccount[state.currentAccountId] = state.expandedFolders;
}

function autoExpand(folders, delimiter) {
  const expanded = {};
  const tree = buildFolderTree(folders, delimiter);
  const walk = node => {
    Object.keys(node.children).forEach(k => {
      const child = node.children[k];
      if (Object.keys(child.children).length) {
        expanded[child.full] = true;
        walk(child);
      }
    });
  };
  walk(tree);
  return expanded;
}

async function loadMessages(append = false) {
  if (!append) showLoading("Cargando correos…");
  try {
    if (!append) state.selected.clear();
    let data;
    if (state.unified) {
      data = await api(`/unified?page=${state.page}&q=${encodeURIComponent(state.q)}&unread_only=${state.unreadOnly}`);
    } else {
      if (!state.currentAccountId) return;
      const qs = `?folder=${encodeURIComponent(state.currentFolder)}&page=${state.page}&q=${encodeURIComponent(state.q)}&unread_only=${state.unreadOnly}`;
      data = await api(`/accounts/${state.currentAccountId}/messages${qs}`);
    }
    if (append) {
      state.messages = [...state.messages, ...data.messages];
    } else {
      state.messages = data.messages;
    }
    state.total = data.total;
    state.lastSync = data.last_sync || null;
    state.hasMore = data.messages.length >= 25;
  } finally {
    hideLoading();
  }
}

function messagesHtml() {
  if (!state.messages.length) return `<div class="empty">Sin mensajes</div>`;
  return state.messages.map(m => {
    const from = m.from[0];
    const sender = from ? (from.name || from.email) : "?";
    const sel = state.selected.has(m.id);
    const ctx = msgCtx(m);
    const accTag = state.unified
      ? `<span class="acc-tag" style="--acc-color:${accColor({ id: m.account_id })}">${esc(m.account_email || m.account_display || "")}</span>`
      : "";
    const icons =
      (m.has_attachments ? '<span class="mc-ico">📎</span>' : "") +
      (m.flagged ? '<span class="mc-ico star">★</span>' : "") +
      (m.spam ? '<span class="spam-badge">SPAM</span>' : "");
    return `
      <div class="msg-card ${m.unread ? "unread" : ""} ${sel ? "selected" : ""}" data-id="${esc(m.id)}" data-acc="${ctx.accountId}" data-folder="${esc(ctx.folder)}" draggable="true">
        <div class="swipe-bg">
          <div class="sb sb-del">🗑</div>
          <div class="sb sb-read">${m.unread ? "✓" : "◌"}</div>
        </div>
        <div class="msg-card-inner">
          ${state.unified ? "" : `<input type="checkbox" class="msg-check" data-id="${esc(m.id)}" ${sel ? "checked" : ""}>`}
          ${avatarFor(sender, from && from.email)}
          <div class="mc-body">
            <div class="mc-row1">
              <span class="mc-from">${esc(sender)}</span>
              <span class="mc-date">${esc(cardDate(m.date))}</span>
            </div>
            <div class="mc-subject">${esc(m.subject)}</div>
            <div class="mc-row2">${accTag}${icons}<button class="move-btn" data-id="${esc(m.id)}" data-acc="${ctx.accountId}" data-folder="${esc(ctx.folder)}" title="Mover a carpeta">📁</button></div>
          </div>
        </div>
      </div>`;
  }).join("");
}

function pagerHtml() {
  const pages = Math.max(1, Math.ceil(state.total / 25));
  return `
    <button class="btn-ghost btn btn-sm" id="btn-prev" ${state.page <= 1 ? "disabled" : ""}>← Anterior</button>
    <span>Página ${state.page} de ${pages} · ${state.total} mensajes</span>
    <button class="btn-ghost btn btn-sm" id="btn-next" ${state.page >= pages ? "disabled" : ""}>Siguiente →</button>`;
}

function bindMessageList() {
  document.querySelectorAll("#message-list .msg-card").forEach(el => {
    const id = el.dataset.id;
    el.onclick = () => {
      if (el._swiped) { el._swiped = false; return; }
      clearTimeout(el._t);
      el._t = setTimeout(() => openMessage(id), 220);
    };
    el.ondblclick = (e) => {
      e.preventDefault();
      if (e.target.classList.contains("msg-check")) return;
      clearTimeout(el._t);
      openMessageModal(id);
    };
    el.addEventListener("dragstart", e => {
      const m0 = state.messages.find(x => x.id === id) || null;
      const ctx = msgCtx(m0);
      dragData = { accountId: ctx.accountId, folder: ctx.folder, uid: id };
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", id);
      el.classList.add("dragging");
    });
    el.addEventListener("dragend", () => {
      el.classList.remove("dragging");
      dragData = null;
    });
    attachSwipe(el, () => quickCardAction(el, "delete"), () => quickCardAction(el, "toggle"));
  });
  document.querySelectorAll(".move-btn").forEach(btn => {
    btn.onclick = (e) => {
      e.stopPropagation();
      const id = btn.dataset.id;
      const accId = parseInt(btn.dataset.acc, 10);
      const folder = btn.dataset.folder;
      showMoveMenu(btn, id, accId, folder);
    };
  });
  document.querySelectorAll(".msg-check").forEach(cb => {
    cb.onclick = (e) => {
      e.stopPropagation();
      const id = cb.dataset.id;
      if (cb.checked) state.selected.add(id);
      else state.selected.delete(id);
      cb.closest(".msg-card").classList.toggle("selected", cb.checked);
      updateBulkBar();
      syncSelectAll();
    };
  });
}

function bindPager() {
  const prev = document.getElementById("btn-prev");
  const next = document.getElementById("btn-next");
  if (prev) prev.onclick = () => { if (state.page > 1) { state.page--; loadMessages().then(renderContent); } };
  if (next) next.onclick = () => { const pages = Math.max(1, Math.ceil(state.total / 25)); if (state.page < pages) { state.page++; loadMessages().then(renderContent); } };
}

let refreshTimer = null;
let refreshing = false;

function silentRefresh() {
  if (refreshing || document.hidden) return;
  if (modalRoot.querySelector(".modal")) return;
  refreshing = true;
  const url = state.unified
    ? `/unified?page=${state.page}&q=${encodeURIComponent(state.q)}&unread_only=${state.unreadOnly}`
    : (state.currentAccountId && state.currentFolder
        ? `/accounts/${state.currentAccountId}/messages?folder=${encodeURIComponent(state.currentFolder)}&page=${state.page}&q=${encodeURIComponent(state.q)}&unread_only=${state.unreadOnly}`
        : null);
  if (!url) { refreshing = false; return; }
  api(url)
    .then(data => {
      state.messages = data.messages;
      state.total = data.total;
      state.lastSync = data.last_sync || null;
      const list = document.getElementById("message-list");
      if (!list) return;
      list.innerHTML = messagesHtml();
      bindMessageList();
      const lu = document.querySelector(".last-update");
      if (lu) lu.textContent = state.lastSync ? "Actualizado " + state.lastSync : "Sin sincronizar";
      const loadMore = document.getElementById("load-more");
      if (loadMore) {
        loadMore.textContent = state.hasMore ? "Cargando más…" : "— Fin de la lista —";
        loadMore.classList.toggle("end", !state.hasMore);
      }
      const badge = document.getElementById("notif-badge");
      if (badge) badge.textContent = state.unreadOnly ? "✓" : (state.messages.reduce((n, m) => n + (m.unread ? 1 : 0), 0) || "");
      syncSelectAll();
      updateBulkBar();
    })
    .catch(() => {})
    .finally(() => { refreshing = false; });
}

function startFolderRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(silentRefresh, 30000);
}

window.addEventListener("message", e => {
  if (e.data && e.data.hmh) {
    const f = document.querySelector(`.body-frame[data-hid="${e.data.hid}"]`);
    if (f) {
      const cur = parseFloat(f.style.height) || 0;
      if (Math.abs(e.data.hmh - cur) > 2) f.style.height = e.data.hmh + "px";
    }
  }
});

function renderShell() {
  const uname = state.user ? (state.user.name || state.user.email || "?") : "?";
  const isAdmin = state.user && state.user.is_admin;
  app.innerHTML = `
    <div class="shell">
      <header class="appbar">
        <button class="icon-btn" id="btn-menu" title="Menú">☰</button>
        <div class="brand appbar-brand"><img src="/engrane.png" class="brand-logo" alt="HUBMail"><span class="appbar-title" id="appbar-title">Bandeja</span></div>
        <div class="appbar-actions">
          <button class="appbar-btn" id="ab-unified" title="Bandeja unificada">📥 <span>Bandeja</span><span class="badge" id="unified-badge"></span></button>
          <button class="appbar-btn" id="ab-compose" title="Redactar">✉️ <span>Redactar</span></button>
          <button class="appbar-btn" id="ab-contacts" title="Contactos">👥 <span>Contactos</span></button>
          <button class="appbar-btn" id="ab-filters" title="Filtros">📁 <span>Filtros</span></button>
          ${isAdmin ? `
            <button class="appbar-btn" id="ab-sync" title="Estado de sincronización">🔄 <span>Sync</span></button>
            <button class="appbar-btn" id="ab-errors" title="Errores de sincronización">⚠️ <span>Errores</span></button>
            <button class="appbar-btn" id="ab-activity" title="Log de actividad">📋 <span>Actividad</span></button>
          ` : ""}
        </div>
        <div class="header-right">
          <button class="icon-btn" id="btn-search" title="Buscar">🔍</button>
          <button class="icon-btn" id="btn-notif" title="No leídos">📬<span class="badge" id="notif-badge"></span></button>
          <button class="icon-btn" id="btn-theme" title="Cambiar tema">${state.theme === "dark" ? "☀️" : "🌙"}</button>
          <button class="icon-btn" id="btn-accounts" title="Cuentas y ajustes">⚙️</button>
          <button class="icon-btn" id="btn-logout" title="Cerrar sesión">⏻</button>
        </div>
      </header>

      <div class="app-body">
        <aside class="sidebar" id="sidebar">
          <div class="sidebar-header">
            <div class="sidebar-user">
              ${avatarFor(state.user && state.user.name, state.user && state.user.email)}
              <div class="sidebar-user-info">
                <div class="sidebar-name" id="btn-welcome" title="Ver mi resumen">${esc(uname)}</div>
                <div class="sidebar-email">${esc(state.user && state.user.email || "")}</div>
              </div>
            </div>
          </div>
          <div class="sec-title">Carpetas</div>
          <div class="sidebar-accounts" id="sidebar-accounts"></div>
        </aside>
        <main id="content"></main>
      </div>

      <button class="fab" id="fab" title="Redactar">✏️</button>
    </div>`;

  const goUnified = () => {
    state.unified = true;
    state.currentFolder = "INBOX";
    state.page = 1;
    state.q = "";
    state.unreadOnly = false;
    state.currentMsgId = null;
    state.hasMore = true;
    state.loadingMore = false;
    closeSidebar();
    loadMessages().then(() => { renderSidebar(); renderContent(); }).catch(e => toast(e.message, "error"));
  };

  function setupInfiniteScroll() {
    const list = document.getElementById("message-list");
    const loadMore = document.getElementById("load-more");
    if (!list || !loadMore) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && state.hasMore && !state.loadingMore) {
        state.loadingMore = true;
        loadMore.textContent = "Cargando más…";
        state.page++;
        loadMessages(true).then(() => {
          list.innerHTML = messagesHtml();
          bindMessageList();
          state.loadingMore = false;
          loadMore.textContent = state.hasMore ? "Cargando más…" : "— Fin de la lista —";
        }).catch(() => {
          state.loadingMore = false;
          loadMore.textContent = "Error al cargar";
        });
      }
    }, { rootMargin: "200px", threshold: 0 });
    observer.observe(loadMore);
  }

  document.getElementById("btn-menu").onclick = openSidebar;
  const drawerOverlay = document.getElementById("drawer-overlay");
  if (drawerOverlay) drawerOverlay.onclick = closeSidebar;
  document.getElementById("fab").onclick = openCompose;
  document.getElementById("btn-search").onclick = focusSearch;
  document.getElementById("btn-accounts").onclick = () => openAccountsModal();
  document.getElementById("btn-theme").onclick = toggleTheme;
  document.getElementById("btn-logout").onclick = logout;
  document.getElementById("ab-unified").onclick = goUnified;
  document.getElementById("ab-compose").onclick = openCompose;
  document.getElementById("ab-contacts").onclick = openContactsManager;
  document.getElementById("ab-filters").onclick = openFiltersManager;
  const elSync = document.getElementById("ab-sync");
  if (elSync) elSync.onclick = () => openAdminSyncStatus();
  const elErr = document.getElementById("ab-errors");
  if (elErr) elErr.onclick = () => openAdminErrors();
  const elAct = document.getElementById("ab-activity");
  if (elAct) elAct.onclick = () => openAdminActivity();
  document.getElementById("btn-welcome").onclick = () => openWelcome();
  document.getElementById("btn-notif").onclick = () => {
    state.unreadOnly = !state.unreadOnly;
    state.page = 1;
    loadMessages().then(renderContent).catch(e => toast(e.message, "error"));
  };
  renderSidebar();
  renderContent();
  applyTheme(state.theme);
}

function buildFolderTree(folders, delimiter) {
  const root = { children: {} };
  folders.forEach(f => {
    const parts = delimiter ? f.name.split(delimiter) : [f.name];
    let node = root;
    let full = "";
    parts.forEach(p => {
      full = full ? full + delimiter + p : p;
      if (!node.children[p]) node.children[p] = { name: p, full, children: {} };
      node = node.children[p];
    });
  });
  return root;
}

function renderFolderTree(node, depth, expanded, accId, unreadMap) {
  let html = "";
  const FOLDER_ORDER = { "INBOX": 0, "ENVIADOS": 1, "SENT": 1, "BOURRONES": 2, "DRAFTS": 2, "SPAM": 3, "JUNK": 3, "PAPELERA": 4, "TRASH": 4, "ELIMINADOS": 4 };
  const names = Object.keys(node.children).sort((a, b) => {
    const ka = node.children[a].name.toUpperCase();
    const kb = node.children[b].name.toUpperCase();
    const pa = ka in FOLDER_ORDER ? FOLDER_ORDER[ka] : 5;
    const pb = kb in FOLDER_ORDER ? FOLDER_ORDER[kb] : 5;
    if (pa !== pb) return pa - pb;
    return node.children[a].name.toLowerCase().localeCompare(node.children[b].name.toLowerCase());
  });
  for (const n of names) {
    const child = node.children[n];
    const hasKids = Object.keys(child.children).length > 0;
    const isActive = state.currentAccountId === accId && state.currentFolder === child.full;
    const pad = 14 + depth * 16;
    const up = child.full.toUpperCase();
    const icon = hasKids ? (expanded[child.full] ? "📂" : "📁") : (up === "INBOX" ? "📥" : "📄");
    const unread = unreadMap ? (unreadMap[child.full] || 0) : 0;
    const badge = `<span class="unread-count" data-unread="${accId}|${esc(child.full)}" style="${unread ? "" : "display:none"}">${unread > 999 ? "999+" : unread}</span>`;
    if (!hasKids) {
      html += `<li class="fitem ${isActive ? "active" : ""}" data-folder="${esc(child.full)}" style="padding-left:${pad}px"><span class="fi-ico">${icon}</span><span class="fi-name">${esc(child.name)}</span>${badge}</li>`;
    } else {
      const open = !!expanded[child.full];
      html += `<li class="fitem fnode ${isActive ? "active" : ""}" style="padding-left:${pad - 6}px">
        <span class="caret" data-caret="${esc(child.full)}">${open ? "▾" : "▸"}</span>
        <span class="fi-ico">${icon}</span>
        <span data-folder="${esc(child.full)}">${esc(child.name)}</span>${badge}
      </li>`;
      if (open) {
        html += `<ul class="folders">${renderFolderTree(child, depth + 1, expanded, accId, unreadMap)}</ul>`;
      }
    }
  }
  return html;
}

function renderSidebar() {
  const wrap = document.getElementById("sidebar-accounts");
  const list = state.accounts.map(acc => {
    const fa = state.foldersByAccount[acc.id] || { folders: [], delimiter: "/" };
    const expanded = state.expandedByAccount[acc.id] || {};
    const collapsed = state.collapsedAccounts.has(acc.id);
    const unreadData = state.unreadByAccount[acc.id] || { folders: [], total: 0 };
    const unreadMap = {};
    (unreadData.folders || []).forEach(f => { unreadMap[f.folder] = f.count; });
    const totalUnread = unreadData.total || 0;
    const tree = collapsed ? "" : renderFolderTree(buildFolderTree(fa.folders, fa.delimiter), 0, expanded, acc.id, unreadMap);
    const isCurrent = !state.unified && state.currentAccountId === acc.id;
    const color = accColor(acc);
    const caret = collapsed ? "▸" : "▾";
    return `
      <div class="account-block" data-acc="${acc.id}" style="--acc-color:${color}">
        <div class="account-head ${isCurrent ? "current" : ""} ${collapsed ? "collapsed" : ""}" data-acc="${acc.id}" title="Clic: colapsar/expandir · Doble clic: abrir">
          <span class="acc-dot" style="background:${color}"></span>
          <div class="acc-main">${esc(acc.display_name || acc.email)}<br><small>${esc(acc.email)}${acc.shared ? ' · <span class="shared-badge">Compartida</span>' : ""}</small></div>
          <span class="acc-unread" data-accunread="${acc.id}" style="${totalUnread ? "" : "display:none"}">${totalUnread > 999 ? "999+" : totalUnread}</span>
          <span class="acc-caret">${caret}</span>
        </div>
        ${tree ? `<div class="sec-title">Carpetas</div><ul class="folders" data-acc="${acc.id}">${tree}</ul>` : ""}
      </div>`;
  }).join("");

  if (wrap) wrap.innerHTML = list;

  const ub = document.getElementById("unified-badge");
  if (ub) {
    const total = state.accounts.reduce((n, a) => n + ((state.unreadByAccount[a.id] || {}).total || 0), 0);
    ub.textContent = total ? (total > 999 ? "999+" : total) : "";
    ub.style.display = total ? "" : "none";
  }

  if (!wrap) return;

  wrap.querySelectorAll(".account-head").forEach(el => {
    el.onclick = () => {
      const id = parseInt(el.dataset.acc);
      if (state.collapsedAccounts.has(id)) state.collapsedAccounts.delete(id);
      else state.collapsedAccounts.add(id);
      renderSidebar();
    };
    el.ondblclick = async () => {
      const id = parseInt(el.dataset.acc);
      state.collapsedAccounts.delete(id);
      state.unified = false;
      state.currentAccountId = id;
      state.currentFolder = "INBOX";
      state.page = 1;
      state.q = "";
      state.unreadOnly = false;
      state.hasMore = true;
      state.loadingMore = false;
      const fa = state.foldersByAccount[id] || { folders: [], delimiter: "/" };
      state.folders = fa.folders;
      state.folderDelimiter = fa.delimiter;
      state.expandedFolders = state.expandedByAccount[id] || {};
      try {
        closeDrawer();
        await loadMessages();
        renderSidebar();
        renderContent();
      } catch (e) { toast(e.message, "error"); }
    };
  });
  wrap.querySelectorAll('[data-folder]').forEach(el => {
    el.onclick = async (e) => {
      e.stopPropagation();
      const accId = parseInt(el.closest("[data-acc]").dataset.acc);
      state.unified = false;
      state.currentMsgId = null;
      if (accId !== state.currentAccountId) {
        state.currentAccountId = accId;
        const fa = state.foldersByAccount[accId] || { folders: [], delimiter: "/" };
        state.folders = fa.folders;
        state.folderDelimiter = fa.delimiter;
        state.expandedFolders = state.expandedByAccount[accId] || {};
      }
      state.currentFolder = el.dataset.folder;
      state.page = 1;
      state.q = "";
      state.unreadOnly = false;
      state.hasMore = true;
      state.loadingMore = false;
      closeDrawer();
      try {
        await loadMessages();
        renderSidebar();
        renderContent();
      } catch (e) { toast(e.message, "error"); }
    };
  });
  wrap.querySelectorAll('[data-caret]').forEach(el => {
    el.onclick = (e) => {
      e.stopPropagation();
      const accId = parseInt(el.closest("[data-acc]").dataset.acc);
      const ex = state.expandedByAccount[accId] || (state.expandedByAccount[accId] = {});
      const key = el.dataset.caret;
      if (ex[key]) delete ex[key];
      else ex[key] = true;
      if (accId === state.currentAccountId) state.expandedFolders = ex;
      renderSidebar();
    };
  });
  bindDropTargets(wrap);
}

function bindDropTargets(sb) {
  const mark = (el, on) => {
    const item = el.closest ? el.closest(".fitem, .account-head") : null;
    if (item) item.classList.toggle("drop-target", on);
  };
  sb.querySelectorAll('[data-folder]').forEach(el => {
    el.addEventListener("dragover", e => { if (dragData) { e.preventDefault(); e.stopPropagation(); mark(el, true); } });
    el.addEventListener("dragleave", () => mark(el, false));
    el.addEventListener("drop", e => {
      e.preventDefault();
      e.stopPropagation();
      mark(el, false);
      if (dragData) doMoveDrop(el.closest("[data-acc]").dataset.acc, el.dataset.folder);
    });
  });
  sb.querySelectorAll(".account-head").forEach(el => {
    el.addEventListener("dragover", e => { if (dragData) { e.preventDefault(); e.stopPropagation(); mark(el, true); } });
    el.addEventListener("dragleave", () => mark(el, false));
    el.addEventListener("drop", e => {
      e.preventDefault();
      e.stopPropagation();
      mark(el, false);
      if (dragData) doMoveDrop(el.dataset.acc, "INBOX");
    });
  });
}

function showMoveMenu(btn, msgId, srcAccId, srcFolder, isBulk = false) {
  const existing = document.getElementById("move-menu");
  if (existing) existing.remove();

  const accounts = state.accounts;
  let html = '<div class="move-menu-header">Mover a carpeta</div>';
  accounts.forEach(acc => {
    const fa = state.foldersByAccount[acc.id] || { folders: [], delimiter: "/" };
    const folders = fa.folders.filter(f => f.name !== srcFolder || acc.id !== srcAccId);
    if (!folders.length) return;
    const color = accColor(acc);
    html += `<div class="move-menu-account" style="--acc-color:${color}">
      <div class="move-menu-account-name">${esc(acc.display_name || acc.email)}</div>
      <div class="move-menu-folders">`;
    folders.forEach(f => {
      html += `<button class="move-menu-folder" data-acc="${acc.id}" data-folder="${esc(f.name)}" data-msgid="${esc(msgId)}" data-srcacc="${srcAccId}" data-srcfolder="${esc(srcFolder)}">${esc(f.name)}</button>`;
    });
    html += '</div></div>';
  });

  const menu = document.createElement("div");
  menu.id = "move-menu";
  menu.className = "move-menu";
  menu.innerHTML = html;
  document.body.appendChild(menu);

  const rect = btn.getBoundingClientRect();
  menu.style.top = (rect.bottom + window.scrollY + 4) + "px";
  const leftPos = isBulk ? (rect.left + window.scrollX - 240) : (rect.left + window.scrollX - 200);
  menu.style.left = leftPos + "px";

  menu.querySelectorAll(".move-menu-folder").forEach(el => {
    el.onclick = async (e) => {
      const destAccId = parseInt(el.dataset.acc);
      const destFolder = el.dataset.folder;
      const uids = state.selected.has(msgId) ? Array.from(state.selected) : [msgId];
      menu.remove();
      await doMoveDrop(destAccId, destFolder);
    };
  });

  const closeMenu = (e) => {
    if (!menu.contains(e.target) && e.target !== btn) {
      menu.remove();
      document.removeEventListener("click", closeMenu);
    }
  };
  setTimeout(() => document.addEventListener("click", closeMenu), 0);
}

async function doMoveDrop(destAccId, destFolder) {
  if (!dragData) return;
  destAccId = parseInt(destAccId);
  const src = dragData;
  dragData = null;
  if (destAccId === src.accountId && destFolder === src.folder) {
    return toast("El mensaje ya está en esa carpeta", "error");
  }
  const uids = state.selected.has(src.uid) ? Array.from(state.selected) : [src.uid];
  showLoading("Moviendo mensaje…");
  try {
    const res = await api("/messages/move", {
      method: "POST",
      body: JSON.stringify({
        source_account_id: src.accountId,
        dest_account_id: destAccId,
        folder: src.folder,
        dest_folder: destFolder,
        uids,
      }),
    });
    state.selected.clear();
    const queued = !!(res && res.queued);
    toast(
      uids.length === 1
        ? (queued ? "Movimiento encolado, se aplicará en la próxima sincronización" : "Mensaje movido")
        : `${uids.length} mensajes movidos${queued ? " (se aplicará en la próxima sincronización)" : ""}`,
      "ok"
    );
    await loadMessages();
    await loadUnreadCounts();
    renderSidebar();
    renderContent();
  } catch (e) {
    toast(e.message, "error");
  } finally {
    hideLoading();
  }
}

function updateHeaderAccount() {
  const t = document.getElementById("appbar-title");
  if (!t) return;
  const pill = (label, col) => `<span class="appbar-acc" style="--acc-color:${col}">${esc(label)}</span>`;
  if (state.unified) {
    const openMsg = state.currentMsgId ? (state.messages.find(x => x.id === state.currentMsgId) || state.currentMsg) : null;
    if (openMsg && openMsg.account_id) {
      const acc = state.accounts.find(a => a.id === openMsg.account_id);
      const label = openMsg.account_display || (acc && (acc.display_name || acc.email)) || openMsg.account_email || "Cuenta";
      const col = accColor(acc || { id: openMsg.account_id });
      t.innerHTML = `<span class="appbar-title-txt">Bandeja</span> ${pill(label, col)}`;
    } else {
      t.textContent = "Bandeja";
    }
    return;
  }
  const acc = state.accounts.find(a => a.id === state.currentAccountId);
  if (!acc) { t.textContent = "HUBMail"; return; }
  const label = state.currentFolder === "INBOX" ? (acc.display_name || acc.email) : state.currentFolder;
  t.innerHTML = pill(label, accColor(acc));
}

function renderContent() {
  const content = document.getElementById("content");
  if (!content) return;
  const curAcc = state.accounts.find(a => a.id === state.currentAccountId);
  if (curAcc) content.style.setProperty("--acc-color", accColor(curAcc));
  updateHeaderAccount();
  const totalUnread = state.messages.reduce((n, m) => n + (m.unread ? 1 : 0), 0);
  const badge = document.getElementById("notif-badge");
  if (badge) badge.textContent = state.unreadOnly ? "✓" : (totalUnread ? totalUnread : "");

  const pages = Math.max(1, Math.ceil(state.total / 25));
  const msgs = messagesHtml();
  const title = state.unified ? "Bandeja unificada" : esc(state.currentFolder);

  content.innerHTML = `
    <div id="list-pane">
      <div class="list-head">
        <div class="list-title-row">
          <div class="folder-title">${title} ${state.unreadOnly ? '<span class="chip chip-unread">No leídos</span>' : ""}</div>
          <div class="last-update">${state.lastSync ? "Actualizado " + esc(state.lastSync) : "Sin sincronizar"}</div>
        </div>
        <div class="list-toolbar">
          <div class="search-wrap">
            <input id="search-box" placeholder="Buscar..." value="${esc(state.q)}">
            ${state.q ? `<button class="search-clear" id="btn-search-clear" title="Limpiar">✕</button>` : ""}
          </div>
          <button class="btn-ghost btn btn-sm" id="btn-unread" title="${state.unreadOnly ? "Mostrar todos" : "Solo no leídos"}">${state.unreadOnly ? "☑ Todo" : "📬 No leídos"}</button>
          <button class="btn-ghost btn btn-sm" id="btn-refresh" title="Refrescar">⟳</button>
        </div>
        ${state.unified ? "" : `
        <div class="bulk-bar" id="bulk-bar">
          <button class="btn-ghost btn btn-sm" id="btn-sel-all">☑ Todo</button>
          <button class="btn-ghost btn btn-sm" id="btn-read-sel">✓ Leído</button>
          <button class="btn-ghost btn btn-sm" id="btn-unread-sel">◌ No leído</button>
          <button class="btn-ghost btn btn-sm" id="btn-move-sel">📁 Mover (<span id="sel-count-move">0</span>)</button>
          <button class="btn-danger btn btn-sm" id="btn-del-sel">🗑 Eliminar (<span id="sel-count">0</span>)</button>
          <button class="btn-ghost btn btn-sm" id="btn-clear-sel">Cancelar</button>
        </div>`}
      </div>
      <div id="message-list">${msgs}</div>
      ${state.hasMore ? `<div class="load-more" id="load-more">Cargando más…</div>` : `<div class="load-more end">— Fin de la lista —</div>`}
    </div>
    <div id="detail-pane"></div>`;

  const searchBox = document.getElementById("search-box");
  let timer;
  searchBox.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      state.q = searchBox.value;
      state.page = 1;
      loadMessages().then(renderContent).catch(e => toast(e.message, "error"));
    }, 500);
  };
  const sc = document.getElementById("btn-search-clear");
  if (sc) sc.onclick = () => { state.q = ""; state.page = 1; loadMessages().then(renderContent).catch(e => toast(e.message, "error")); };
  if (!state.unified) {
    const selAll = document.getElementById("sel-all");
    if (selAll) {
      selAll.onchange = () => {
        if (selAll.checked) state.messages.forEach(m => state.selected.add(m.id));
        else state.messages.forEach(m => state.selected.delete(m.id));
        renderContent();
      };
    }
  }
  syncSelectAll();
  document.getElementById("btn-refresh").onclick = () => {
    state.page = 1;
    const jobs = [loadMessages()];
    if (!state.unified) jobs.push(loadFolders());
    Promise.all(jobs).then(() => { renderContent(); renderSidebar(); }).catch(e => toast(e.message, "error"));
  };
  document.getElementById("btn-unread").onclick = () => {
    state.unreadOnly = !state.unreadOnly;
    state.page = 1;
    loadMessages().then(renderContent).catch(e => toast(e.message, "error"));
  };

  bindMessageList();
  setupInfiniteScroll();
  if (!state.unified) {
    document.getElementById("btn-sel-all").onclick = () => {
      if (state.selected.size === state.messages.length) state.selected.clear();
      else state.messages.forEach(m => state.selected.add(m.id));
      renderContent();
    };
    document.getElementById("btn-clear-sel").onclick = () => {
      state.selected.clear();
      renderContent();
    };
    document.getElementById("btn-del-sel").onclick = async () => {
      const n = state.selected.size;
      if (!n) return;
      if (!confirm(`¿Eliminar ${n} mensaje(s) definitivamente? Esta acción no se puede deshacer.`)) return;
      showLoading("Eliminando mensajes…");
      try {
        await api(`/accounts/${state.currentAccountId}/messages/bulk-delete`, {
          method: "POST",
          body: JSON.stringify({ folder: state.currentFolder, ids: [...state.selected] }),
        });
        state.selected.clear();
        await loadMessages();
        renderContent();
        toast(`${n} mensaje(s) eliminado(s)`, "ok");
      } catch (e) {
        toast(e.message, "error");
      } finally {
        hideLoading();
      }
    };
    const setBulkSeen = async (seen) => {
      const n = state.selected.size;
      if (!n) return;
      showLoading(seen ? "Marcando como leído…" : "Marcando como no leído…");
      try {
        await api(`/accounts/${state.currentAccountId}/messages/bulk-seen`, {
          method: "POST",
          body: JSON.stringify({ folder: state.currentFolder, ids: [...state.selected], seen }),
        });
        state.selected.clear();
        await loadMessages();
        renderContent();
        toast(seen ? `${n} mensaje(s) leídos` : `${n} mensaje(s) marcados como no leídos`, "ok");
      } catch (e) {
        toast(e.message, "error");
      } finally {
        hideLoading();
      }
    };
    document.getElementById("btn-read-sel").onclick = () => setBulkSeen(true);
    document.getElementById("btn-unread-sel").onclick = () => setBulkSeen(false);
    document.getElementById("btn-move-sel").onclick = () => {
      if (!state.selected.size) return;
      const firstMsg = state.messages.find(m => state.selected.has(m.id));
      if (firstMsg) {
        const ctx = msgCtx(firstMsg);
        showMoveMenu(document.getElementById("btn-move-sel"), [...state.selected][0], ctx.accountId, ctx.folder, true);
      }
    };
    updateBulkBar();
  }

  const dp = document.getElementById("detail-pane");
  if (state.currentMsgId) {
    const m0 = state.messages.find(x => x.id === state.currentMsgId) || state.currentMsg;
    const ctx = msgCtx(m0);
    loadMessageDetail(state.currentMsgId, ctx.accountId, ctx.folder).then(m => {
      m.account_id = ctx.accountId;
      m.folder = ctx.folder;
      if (document.getElementById("detail-pane")) renderDetail(m);
    }).catch(() => {});
  } else {
    dp.innerHTML = `<div class="empty" style="margin-top:80px">Selecciona un mensaje para leerlo</div>`;
    dp.classList.remove("open");
  }
}

function updateBulkBar() {
  const bar = document.getElementById("bulk-bar");
  const count = document.getElementById("sel-count");
  const countMove = document.getElementById("sel-count-move");
  if (bar) bar.style.display = state.selected.size ? "flex" : "none";
  if (count) count.textContent = state.selected.size;
  if (countMove) countMove.textContent = state.selected.size;
}

function syncSelectAll() {
  const cb = document.getElementById("sel-all");
  if (!cb) return;
  const n = state.messages.length;
  const sel = state.messages.filter(m => state.selected.has(m.id)).length;
  cb.checked = n > 0 && sel === n;
  cb.indeterminate = n > 0 && sel > 0 && sel < n;
}

async function openMessage(id) {
  const m0 = state.messages.find(x => x.id === id) || null;
  state.currentMsg = m0;
  const ctx = msgCtx(m0);
  state.currentMsgId = id;
  showLoading("Cargando mensaje…");
  try {
    const m = await loadMessageDetail(id, ctx.accountId, ctx.folder);
    m.account_id = ctx.accountId;
    m.folder = ctx.folder;
    renderDetail(m);
    if (m.unread) {
      api(`/accounts/${ctx.accountId}/messages/${encodeURIComponent(id)}?folder=${encodeURIComponent(ctx.folder)}&action=read`, { method: "PATCH" }).catch(() => {});
      state.messages.forEach(x => { if (x.id === id) x.unread = false; });
      renderContent();
      loadUnreadCounts().catch(() => {});
    }
  } catch (e) {
    toast(e.message, "error");
  } finally {
    hideLoading();
  }
}

async function setMessageSeen(id, seen) {
  const m0 = state.messages.find(x => x.id === id) || null;
  const ctx = msgCtx(m0);
  try {
    await api(`/accounts/${ctx.accountId}/messages/${encodeURIComponent(id)}?folder=${encodeURIComponent(ctx.folder)}&action=${seen ? "read" : "unread"}`, { method: "PATCH" });
    state.messages.forEach(x => { if (x.id === id) x.unread = !seen; });
    const el = document.querySelector(`#message-list .msg-card[data-id="${esc(id)}"]`);
    if (el) el.classList.toggle("unread", !seen);
    toast(seen ? "Marcado como leído" : "Marcado como no leído", "ok");
    loadUnreadCounts().catch(() => {});
  } catch (e) {
    toast(e.message, "error");
  }
}

async function loadMessageDetail(id, accountId, folder) {
  accountId = accountId || state.currentAccountId;
  folder = folder || state.currentFolder;
  return api(`/accounts/${accountId}/messages/${encodeURIComponent(id)}?folder=${encodeURIComponent(folder)}`);
}

function proxyImages(html) {
  if (!state.token) return html;
  return html.replace(/src=(["'])(https?:\/\/[^"']+)\1/gi, (m, q, url) =>
    `src=${q}/api/img?t=${encodeURIComponent(state.token)}&url=${encodeURIComponent(url)}${q}`);
}

function detailHtml(m) {
  const from = m.from[0];
  const sender = from ? `${esc(from.name || "")} &lt;${esc(from.email)}&gt;` : "";
  const to = m.to.map(t => `<span class="chip">${esc(t.name || t.email)}</span>`).join("");
  const cc = m.cc.length ? `<div class="detail-meta">CC: ${m.cc.map(t => esc(t.name || t.email)).join(", ")}</div>` : "";
  const accTag = m.account_email ? `<span class="acc-tag" style="--acc-color:${accColor({ id: m.account_id })}">${esc(m.account_email)}</span> ` : "";
  const atts = m.attachments.length
    ? `<div class="attachments"><div class="att-title">Adjuntos (${m.attachments.length})</div>${m.attachments.map(a => {
        if (a.cid) return "";
        return `<a class="att-item" download="${esc(a.name)}" href="data:${a.content_type};base64,${a.data}"><span>📎</span><span class="att-name">${esc(a.name)}</span> <span>(${fmtSize(a.size)})</span></a>`;
      }).join("")}</div>`
    : "";
  const inlineImages = m.attachments.filter(a => a.cid);
  let bodyHtml = m.body_html;
  inlineImages.forEach(a => {
    bodyHtml = bodyHtml.replace(new RegExp("cid:" + a.cid.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g"), `data:${a.content_type};base64,${a.data}`);
  });
  bodyHtml = proxyImages(bodyHtml);
  m._bodyRendered = bodyHtml || m.body_text || "";

  return `
    <div class="detail-toolbar">
      <button class="btn-ghost btn btn-sm" id="d-back" title="Volver">←</button>
      <button class="btn-ghost btn btn-sm" id="d-reply" title="Responder">↩<span class="btn-label">Responder</span></button>
      <button class="btn-ghost btn btn-sm" id="d-fwd" title="Reenviar">↪<span class="btn-label">Reenviar</span></button>
      <button class="btn-ghost btn btn-sm" id="d-translate" title="Traducir a español">🌐<span class="btn-label">Traducir</span></button>
      <button class="btn-ghost btn btn-sm" id="d-flag" title="Marcar/desmarcar">${m.flagged ? "★" : "☆"}</button>
      <button class="btn-ghost btn btn-sm" id="d-unread" title="Marcar como no leído">◌<span class="btn-label">No leído</span></button>
      <button class="btn-ghost btn btn-sm" id="d-print" title="Imprimir">🖨<span class="btn-label">Imprimir</span></button>
      <button class="btn-ghost btn btn-sm" id="d-notspam" title="No es spam" style="display:${m.spam ? "" : "none"}">🚫<span class="btn-label">No es spam</span></button>
      <span class="detail-zoom">
        <button class="btn-ghost btn btn-sm" id="d-zoomout" title="Alejar">−</button>
        <span class="detail-zoom-val" id="d-zoom-val">100%</span>
        <button class="btn-ghost btn btn-sm" id="d-zoomin" title="Acercar">+</button>
      </span>
      <span class="spacer"></span>
      <button class="btn-ghost btn btn-sm" id="d-move" title="Mover a carpeta">📁<span class="btn-label">Mover</span></button>
      <button class="btn-ghost btn btn-sm" id="d-filter" title="Crear filtro a partir de este mensaje">⛭<span class="btn-label">Crear filtro</span></button>
      <button class="btn-danger btn btn-sm" id="d-del" title="Eliminar">🗑</button>
    </div>
    <div class="detail-body">
      <div class="detail-head">
        ${avatarFor(from && (from.name || from.email), from && from.email)}
        <div class="dh-main">
          <div class="detail-subject">${esc(m.subject)}</div>
          <div class="detail-from">${accTag}${sender}</div>
          <div class="detail-meta">Para: ${to}</div>
          ${cc}
          <div class="detail-meta">Fecha: ${esc(m.date)}</div>
        </div>
      </div>
      ${atts}
      ${bodyFrameHtml(m)}
    </div>`;
}

function bodyFrameHtml(m) {
  const fId = "bf-" + Math.random().toString(36).slice(2, 8);
  const autoH = `<script>(function(){var w=-1;function r(){var h=document.documentElement.scrollHeight||document.body.scrollHeight;if(h!==w){w=h;parent.postMessage({hmh:h,hid:"${fId}"},"*")}}if(window.addEventListener){window.addEventListener("load",function(){setTimeout(r,40)});window.addEventListener("resize",r);window.addEventListener("message",function(e){var d=e.data;if(d&&d.hid==="${fId}"&&d.zoom){document.documentElement.style.zoom=d.zoom;setTimeout(r,100)}})}setTimeout(r,150)})()<\/script>`;
  const html = (m._translated ? m._translatedHtml : m._bodyRendered) || "";
  return `<iframe class="body-frame" data-hid="${fId}" sandbox="allow-scripts" referrerpolicy="no-referrer" srcdoc="${esc(html + autoH)}"></iframe>`;
}

function normalizeText(s) {
  return String(s || "").replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}

async function toggleTranslate(m) {
  const btn = document.getElementById("d-translate");
  if (m._translated) {
    m._translated = false;
    const frame = document.querySelector(".body-frame");
    if (frame) frame.outerHTML = bodyFrameHtml(m);
    if (btn) btn.innerHTML = "🌐<span class=\"btn-label\">Traducir</span>";
    return;
  }
  if (!btn) return;
  const html = m._bodyRendered || m.body_html || m.body_text || "";
  if (!html.trim()) return toast("Este mensaje no tiene contenido para traducir", "error");
  btn.disabled = true;
  btn.innerHTML = "…";
  try {
    const res = await api("/translate", {
      method: "POST",
      body: JSON.stringify({ text: html, html: true }),
    });
    if (normalizeText(res.translated) === normalizeText(html)) {
      toast("El mensaje ya está en español", "ok");
    } else {
      m._translatedHtml = res.translated;
      m._translated = true;
      const frame = document.querySelector(".body-frame");
      if (frame) frame.outerHTML = bodyFrameHtml(m);
      if (btn) btn.innerHTML = "🌐<span class=\"btn-label\">Ver original</span>";
      if (res.remaining !== undefined && res.remaining !== null && res.remaining < 10000) {
        toast("Quedan pocos caracteres de traducción: " + res.remaining, "");
      }
    }
  } catch (e) {
    toast(e.message, "error");
  } finally {
    btn.disabled = false;
    if (!m._translated) btn.innerHTML = "🌐<span class=\"btn-label\">Traducir</span>";
  }
}

function renderDetail(m) {
  const dp = document.getElementById("detail-pane");
  dp.innerHTML = detailHtml(m);
  dp.classList.add("open");
  bindDetailActions(m);
  updateHeaderAccount();
}

function bindDetailActions(m) {
  const ctx = msgCtx(m);
  const isModal = !!modalRoot.querySelector(".modal");
  const dp = document.getElementById("detail-pane");
  let zoom = 1;
  const setZoom = z => {
    zoom = Math.min(2, Math.max(0.4, z));
    const val = document.getElementById("d-zoom-val");
    if (val) val.textContent = Math.round(zoom * 100) + "%";
    const frame = document.querySelector(".body-frame");
    if (frame && frame.contentWindow) frame.contentWindow.postMessage({ hid: frame.dataset.hid, zoom }, "*");
  };
  const zo = document.getElementById("d-zoomout");
  if (zo) zo.onclick = () => setZoom(zoom - 0.1);
  const zi = document.getElementById("d-zoomin");
  if (zi) zi.onclick = () => setZoom(zoom + 0.1);
  document.getElementById("d-back").onclick = () => {
    state.currentMsgId = null;
    if (isModal) closeModal();
    else if (dp) {
      dp.classList.remove("open");
      dp.innerHTML = `<div class="empty" style="margin-top:80px">Selecciona un mensaje para leerlo</div>`;
    }
    updateHeaderAccount();
  };
  document.getElementById("d-del").onclick = async () => {
    if (!confirm("¿Eliminar este mensaje?")) return;
    await api(`/accounts/${ctx.accountId}/messages/${encodeURIComponent(m.id)}?folder=${encodeURIComponent(ctx.folder)}&action=delete`, { method: "PATCH" }).catch(e => toast(e.message, "error"));
    state.currentMsgId = null;
    await loadMessages();
    renderContent();
    if (isModal) closeModal();
    toast("Mensaje eliminado", "ok");
  };
  document.getElementById("d-flag").onclick = async () => {
    await api(`/accounts/${ctx.accountId}/messages/${encodeURIComponent(m.id)}?folder=${encodeURIComponent(ctx.folder)}&action=${m.flagged ? "unflag" : "flag"}`, { method: "PATCH" }).catch(() => {});
    m.flagged = !m.flagged;
    document.getElementById("d-flag").textContent = m.flagged ? "★" : "☆";
  };
  document.getElementById("d-unread").onclick = async () => {
    await api(`/accounts/${ctx.accountId}/messages/${encodeURIComponent(m.id)}?folder=${encodeURIComponent(ctx.folder)}&action=unread`, { method: "PATCH" }).catch(() => {});
    m.unread = true;
    state.messages.forEach(x => { if (x.id === m.id) x.unread = true; });
    const el = document.querySelector(`#message-list .msg-card[data-id="${esc(m.id)}"]`);
    if (el) el.classList.add("unread");
    toast("Marcado como no leído", "ok");
  };
  document.getElementById("d-reply").onclick = () => {
    const f = m.from[0];
    openCompose({ to: [f && f.email], subject: m.subject.startsWith("Re:") ? m.subject : "Re: " + m.subject, reply_to: m.message_id });
  };
  document.getElementById("d-fwd").onclick = () => {
    openCompose({ subject: m.subject.startsWith("Fwd:") ? m.subject : "Fwd: " + m.subject });
  };
  const dtr = document.getElementById("d-translate");
  if (dtr) dtr.onclick = () => toggleTranslate(m);
  document.getElementById("d-print").onclick = () => printMessage(m);
  const df = document.getElementById("d-filter");
  if (df) df.onclick = () => {
    const from = m.from[0];
    const email = from && from.email;
    openFilterForm(null, {
      name: email ? "Mensajes de " + email : "Filtro desde mensaje",
      conditions: [{ field: "from", op: "contains", value: email || "" }],
    });
  };
  const dm = document.getElementById("d-move");
  if (dm) dm.onclick = () => showMoveMenu(dm, m.id, ctx.accountId, ctx.folder);
  const ns = document.getElementById("d-notspam");
  if (ns) ns.onclick = async () => {
    await api(`/accounts/${ctx.accountId}/messages/${encodeURIComponent(m.id)}?folder=${encodeURIComponent(ctx.folder)}&action=notspam`, { method: "PATCH" }).catch(e => toast(e.message, "error"));
    m.spam = false;
    document.getElementById("d-notspam").style.display = "none";
    toast("Marcado como no spam", "ok");
  };
}

function printMessage(m) {
  const from = m.from[0];
  const to = m.to.map(t => t.name || t.email).join(", ");
  const cc = m.cc.length ? `<p><b>CC:</b> ${esc(m.cc.map(t => t.name || t.email).join(", "))}</p>` : "";
  const atts = m.attachments.filter(a => !a.cid).map(a => esc(a.name)).join(", ");
  const inlineImages = m.attachments.filter(a => a.cid);
  let bodyHtml = m.body_html || "";
  inlineImages.forEach(a => {
    bodyHtml = bodyHtml.replace(new RegExp("cid:" + a.cid.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g"), `data:${a.content_type};base64,${a.data}`);
  });
  bodyHtml = proxyImages(bodyHtml);
  const w = window.open("", "_blank", "width=900,height=700");
  if (!w) return toast("Permite ventanas emergentes para imprimir", "error");
  w.document.write(`<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>${esc(m.subject)}</title>
<style>
  body { font-family: Arial, Helvetica, sans-serif; color: #222; margin: 28px; }
  .h { border-bottom: 2px solid #1a2b49; padding-bottom: 10px; margin-bottom: 16px; }
  .h h1 { font-size: 18px; color: #1a2b49; margin: 0 0 10px; }
  .meta { font-size: 12px; color: #555; line-height: 1.5; }
  .meta p { margin: 2px 0; }
  .meta b { color: #333; }
  .body { margin-top: 18px; font-size: 13px; line-height: 1.5; }
  .body img { max-width: 100%; }
</style>
</head>
<body>
  <div class="h">
    <h1>${esc(m.subject)}</h1>
    <div class="meta">
      <p><b>De:</b> ${esc(from ? (from.name || from.email) : "")} &lt;${esc(from ? from.email : "")}&gt;</p>
      <p><b>Para:</b> ${esc(to)}</p>
      ${cc}
      <p><b>Fecha:</b> ${esc(m.date)}</p>
      ${atts ? `<p><b>Adjuntos:</b> ${esc(atts)}</p>` : ""}
    </div>
  </div>
  <div class="body">${bodyHtml}</div>
  <script>window.onload = function(){ window.focus(); window.print(); };</script>
</body>
</html>`);
  w.document.close();
}

async function openMessageModal(id) {
  const dp = document.getElementById("detail-pane");
  if (dp) dp.classList.remove("open");
  const m0 = state.messages.find(x => x.id === id) || null;
  const ctx = msgCtx(m0);
  state.currentMsgId = null;
  showLoading("Cargando mensaje…");
  try {
    const m = await loadMessageDetail(id, ctx.accountId, ctx.folder);
    m.account_id = ctx.accountId;
    m.folder = ctx.folder;
    openModal(detailHtml(m), "modal-email");
    bindDetailActions(m);
  } catch (e) {
    toast(e.message, "error");
  } finally {
    hideLoading();
  }
}

function fmtSize(n) {
  if (n > 1048576) return (n / 1048576).toFixed(1) + " MB";
  if (n > 1024) return (n / 1024).toFixed(0) + " KB";
  return n + " B";
}

/* ============================================================ compose */
function initRecipientAutocomplete(el) {
  let timer = null, box = null, items = [], sel = -1;
  const wrap = el.parentElement;
  const lastToken = () => {
    const v = el.value.split(",");
    return (v[v.length - 1] || "").trim();
  };
  const replaceToken = email => {
    const v = el.value.split(",");
    v[v.length - 1] = email;
    el.value = v.join(", ").replace(/,+\s*$/, "");
    close();
    el.focus();
  };
  const close = () => {
    if (box) { box.remove(); box = null; }
    items = [];
    sel = -1;
  };
  const renderList = () => {
    box.innerHTML = items.map((it, i) =>
      `<div class="ac-item ${i === sel ? "active" : ""}" data-i="${i}"><b>${esc(it.name || it.email)}</b><span class="c-email">${esc(it.email)}</span></div>`).join("");
    box.querySelectorAll(".ac-item").forEach(d => d.onclick = () => replaceToken(items[parseInt(d.dataset.i)].email));
  };
  const open = list => {
    close();
    if (!list.length) return;
    items = list;
    box = document.createElement("div");
    box.className = "ac-drop";
    renderList();
    wrap.appendChild(box);
  };
  el.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = lastToken();
      if (q.length < 2) return close();
      try {
        const res = await api("/contacts/autocomplete?q=" + encodeURIComponent(q));
        open(res.items || []);
      } catch (e) {}
    }, 160);
  });
  el.addEventListener("keydown", e => {
    if (!box || !items.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); sel = (sel + 1) % items.length; renderList(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); sel = (sel - 1 + items.length) % items.length; renderList(); }
    else if (e.key === "Enter") { e.preventDefault(); if (sel >= 0) replaceToken(items[sel].email); }
    else if (e.key === "Escape") close();
  });
  el.addEventListener("blur", () => setTimeout(close, 150));
}

function openCompose(prefill = {}) {
  const defAcc = state.accounts.find(a => a.is_default) || state.accounts[0];
  const accOptions = state.accounts.map(a =>
    `<option value="${a.id}" ${a.id === (defAcc && defAcc.id) ? "selected" : ""}>${esc(a.email)}</option>`).join("");
  state.composeAttachments = [];
  openModal(`
    <h2>Nuevo mensaje</h2>
    <div class="compose-row"><label>De:</label><select id="c-from">${accOptions}</select></div>
    <div class="compose-row"><label>Para:</label><input id="c-to" value="${esc((prefill.to || []).join(", "))}" placeholder="correo@dominio.com"></div>
    <div class="compose-row"><label>CC:</label><input id="c-cc" placeholder="opcional"></div>
    <div class="compose-row"><label>Asunto:</label><input id="c-subject" value="${esc(prefill.subject || "")}"></div>
    <div class="compose-row"><label>Adj:</label><input type="file" id="c-files" multiple></div>
    <div class="attach-list" id="c-attach-list"></div>
    <div class="compose-row"><label></label><label class="rec-check"><input type="checkbox" id="c-receipt"> Solicitar confirmación de lectura</label></div>
    <div id="compose-body" contenteditable="true" spellcheck="true" lang="es-MX" data-placeholder="Escribe tu mensaje..."></div>
    <div class="actions">
      <button class="btn-ghost btn" id="c-contacts">👥 Contactos</button>
      <button class="btn-ghost btn" id="c-translate">🌐 Traducir</button>
      <span class="spacer"></span>
      <button class="btn-ghost btn" id="c-cancel">Cancelar</button>
      <button class="btn-primary btn" id="c-send">Enviar</button>
    </div>`, "modal-wide");

  document.getElementById("c-cancel").onclick = closeModal;
  document.getElementById("c-send").onclick = () => sendMessage();
  document.getElementById("c-files").onchange = e => {
    const maxMB = 25;
    const total = [...e.target.files].reduce((n, f) => n + f.size, 0);
    if (total > maxMB * 1024 * 1024) return toast("Los adjuntos superan los " + maxMB + " MB", "error");
    [...e.target.files].forEach(f => {
      const reader = new FileReader();
      reader.onload = () => {
        state.composeAttachments.push({
          name: f.name,
          content_type: f.type || "application/octet-stream",
          data: reader.result.split(",")[1],
          size: f.size,
        });
        renderAttachList();
      };
      reader.readAsDataURL(f);
    });
  };
  document.getElementById("c-contacts").onclick = () => openContactsManager(true);
  document.getElementById("c-translate").onclick = () => translateCompose();
  insertSignature();
  initRecipientAutocomplete(document.getElementById("c-to"));
  initRecipientAutocomplete(document.getElementById("c-cc"));
}

function composeAccount() {
  const sel = document.getElementById("c-from");
  return state.accounts.find(a => a.id === parseInt(sel ? sel.value : 0)) || state.accounts[0];
}

function insertSignature() {
  const body = document.getElementById("compose-body");
  if (!body) return;
  body.querySelectorAll(".hub-sig").forEach(el => el.remove());
  if (!state.signature_html) return;
  const wrap = document.createElement("div");
  wrap.className = "hub-sig";
  wrap.innerHTML = `<div><br></div><div><br></div><div><br></div>${state.signature_html}`;
  body.appendChild(wrap);
}

function bodyHtmlToSend() {
  const body = document.getElementById("compose-body");
  const clone = body.cloneNode(true);
  clone.querySelectorAll(".hub-sig").forEach(b => {
    while (b.firstChild) b.parentNode.insertBefore(b.firstChild, b);
    b.remove();
  });
  return clone.innerHTML;
}

async function translateCompose() {
  const body = document.getElementById("compose-body");
  if (!body) return;
  const clone = body.cloneNode(true);
  let sig = null;
  clone.querySelectorAll(".hub-sig").forEach(s => { sig = s; s.remove(); });
  const html = clone.innerHTML.trim();
  if (!html) return toast("No hay contenido para traducir", "error");
  const btn = document.getElementById("c-translate");
  const oldLabel = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = "Traduciendo…";
  try {
    const res = await api("/translate", {
      method: "POST",
      body: JSON.stringify({ text: html, html: true }),
    });
    if (normalizeText(res.translated) === normalizeText(html)) {
      toast("El mensaje ya está en español", "ok");
    } else {
      body.innerHTML = res.translated;
      if (sig) body.appendChild(sig);
      toast("Mensaje traducido", "ok");
    }
  } catch (e) {
    toast(e.message, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = oldLabel;
  }
}

function renderAttachList() {
  const el = document.getElementById("c-attach-list");
  el.innerHTML = state.composeAttachments.map((a, i) =>
    `<span class="attach-chip">📎 ${esc(a.name)} (${fmtSize(a.size)}) <button class="btn-sm btn-danger" data-i="${i}">✕</button></span>`).join("");
  el.querySelectorAll("[data-i]").forEach(b => {
    b.onclick = () => {
      state.composeAttachments.splice(parseInt(b.dataset.i), 1);
      renderAttachList();
    };
  });
}

async function sendMessage() {
  const to = document.getElementById("c-to").value.split(",").map(s => s.trim()).filter(Boolean);
  const cc = document.getElementById("c-cc").value.split(",").map(s => s.trim()).filter(Boolean);
  const subject = document.getElementById("c-subject").value;
  const accountId = parseInt(document.getElementById("c-from").value);
  if (!to.length) return toast("Indica al menos un destinatario", "error");
  const bodyHtml = bodyHtmlToSend();
  const btn = document.getElementById("c-send");
  btn.disabled = true;
  btn.textContent = "Enviando...";
  showLoading("Enviando correo…");
  try {
    const res = await api(`/accounts/${accountId}/send`, {
      method: "POST",
      body: JSON.stringify({ to, cc, subject, body_html: bodyHtml, attachments: state.composeAttachments, read_receipt: document.getElementById("c-receipt").checked }),
    });
    closeModal();
    toast(res && res.queued_sent ? "Correo enviado (se guardará en Enviados)" : "Correo enviado", "ok");
  } catch (e) {
    toast(e.message, "error");
    btn.disabled = false;
    btn.textContent = "Enviar";
  } finally {
    hideLoading();
  }
}

/* ============================================================ contactos */
function useContact(email) {
  const to = document.getElementById("c-to");
  if (to) {
    to.value = to.value ? to.value + ", " + email : email;
    return;
  }
  openCompose({ to: [email] });
}

async function openContactsManager(pickMode = false) {
  let data;
  showLoading("Cargando contactos…");
  try {
    data = await api("/contacts");
  } catch (e) {
    hideLoading();
    return toast(e.message, "error");
  }
  hideLoading();
  const rows = [];
  (data.users || []).forEach(u => rows.push({ kind: "user", name: u.name, email: u.email }));
  (data.addressbook || []).forEach(a => rows.push({ kind: "auto", id: a.id, name: a.name || a.email, email: a.email }));
  (data.contacts || []).forEach(c => rows.push({ kind: "saved", id: c.id, name: c.name, email: c.email }));

  const originBadge = kind =>
    kind === "user" ? '<span class="badge-origin badge-user">ECCSA</span>'
    : kind === "auto" ? '<span class="badge-origin badge-auto">Recopilado</span>'
    : '<span class="badge-origin badge-saved">Guardado</span>';

  openModal(`
    <h2>Contactos</h2>
    <div class="contacts-toolbar">
      <input id="ct-search" placeholder="🔍 Buscar por nombre o correo…">
      <button class="btn-primary btn" id="ct-new">+ Agregar</button>
    </div>
    <div class="table-wrap">
      <table class="contacts-table">
        <thead><tr><th>Nombre</th><th>Correo</th><th>Origen</th><th class="th-actions">Acciones</th></tr></thead>
        <tbody id="ct-tbody"></tbody>
      </table>
    </div>
    <div class="empty" id="ct-empty" style="display:none">Sin resultados</div>
    <div class="contacts-foot">
      <span class="ct-count" id="ct-count"></span>
      <span class="spacer"></span>
      <button class="btn-ghost btn" id="ct-close">Cerrar</button>
    </div>`, "modal-wide");

  const tbody = document.getElementById("ct-tbody");
  const countEl = document.getElementById("ct-count");
  const emptyEl = document.getElementById("ct-empty");

  const renderRows = q => {
    const term = (q || "").toLowerCase().trim();
    const filtered = rows.filter(r =>
      !term || r.name.toLowerCase().includes(term) || r.email.toLowerCase().includes(term));
    tbody.innerHTML = filtered.map(r => {
      const actions = [];
      if (pickMode) actions.push(`<button class="btn-ghost btn btn-sm" data-act="use" data-email="${esc(r.email)}">Usar</button>`);
      if (r.kind !== "user") {
        actions.push(`<button class="btn-ghost btn btn-sm" data-act="edit" data-kind="${r.kind}" data-id="${r.id}" title="Editar">✎</button>`);
        actions.push(`<button class="btn-danger btn btn-sm" data-act="del" data-kind="${r.kind}" data-id="${r.id}" title="Eliminar">🗑</button>`);
      }
      return `<tr>
        <td class="td-name">${esc(r.name)}</td>
        <td class="td-email">${esc(r.email)}</td>
        <td>${originBadge(r.kind)}</td>
        <td class="td-actions">${actions.join("")}</td>
      </tr>`;
    }).join("");
    countEl.textContent = `${filtered.length} de ${rows.length} contactos`;
    emptyEl.style.display = filtered.length ? "none" : "";
  };
  renderRows("");

  document.getElementById("ct-close").onclick = closeModal;
  document.getElementById("ct-new").onclick = () => openContactForm(null, pickMode);
  document.getElementById("ct-search").oninput = e => renderRows(e.target.value);
  tbody.addEventListener("click", e => {
    const btn = e.target.closest("[data-act]");
    if (!btn) return;
    const { act, email, id, kind } = btn.dataset;
    if (act === "use") { closeModal(); useContact(email); }
    else if (act === "edit") {
      const row = rows.find(r => r.id === parseInt(id));
      if (kind === "auto") openContactForm({ kind: "auto", id: parseInt(id), name: row?.name, email: row?.email }, pickMode);
      else openContactForm(data.contacts.find(x => x.id === parseInt(id)), pickMode);
    }
    else if (act === "del") {
      if (!confirm(`¿Eliminar este ${kind === "auto" ? "contacto recopilado" : "contacto"}?`)) return;
      const url = kind === "auto" ? `/addressbook/${id}` : `/contacts/${id}`;
      api(url, { method: "DELETE" })
        .then(() => { toast("Contacto eliminado", "ok"); openContactsManager(pickMode); })
        .catch(e => toast(e.message, "error"));
    }
  });
}

function openContactForm(c, pickMode) {
  const isAuto = c && c.kind === "auto";
  openModal(`
    <h2>${isAuto ? "Editar contacto recopilado" : c ? "Editar contacto" : "Nuevo contacto"}</h2>
    ${isAuto ? '<p class="admin-hint">Solo puedes cambiar el nombre. El correo se recopila automáticamente de tus mensajes.</p>' : ""}
    <div class="field"><label>Nombre</label><input id="cf-name" value="${esc(c?.name || "")}"></div>
    <div class="field"><label>Email</label><input id="cf-email" value="${esc(c?.email || "")}" ${isAuto ? "readonly" : ""}></div>
    ${isAuto ? "" : `<div class="field"><label>Teléfono</label><input id="cf-phone" value="${esc(c?.phone || "")}"></div>
    <div class="field"><label>Notas</label><textarea id="cf-notes">${esc(c?.notes || "")}</textarea></div>`}
    <div class="actions">
      <button class="btn-ghost btn" id="cf-cancel">Cancelar</button>
      <button class="btn-primary btn" id="cf-save">Guardar</button>
    </div>`);
  document.getElementById("cf-cancel").onclick = () => openContactsManager(pickMode);
  document.getElementById("cf-save").onclick = async () => {
    const payload = {
      name: document.getElementById("cf-name").value.trim(),
      email: document.getElementById("cf-email").value.trim(),
      phone: (document.getElementById("cf-phone")?.value || "").trim(),
      notes: (document.getElementById("cf-notes")?.value || "").trim(),
    };
    if (!payload.name || !payload.email) return toast("Nombre y email son obligatorios", "error");
    try {
      if (isAuto) await api(`/addressbook/${c.id}`, { method: "PUT", body: JSON.stringify(payload) });
      else if (c) await api(`/contacts/${c.id}`, { method: "PUT", body: JSON.stringify(payload) });
      else await api("/contacts", { method: "POST", body: JSON.stringify(payload) });
      toast("Contacto guardado", "ok");
    } catch (e) { toast(e.message, "error"); }
    openContactsManager(pickMode);
  };
}

/* ============================================================ accounts */
function openAccountsModal() {
  const isAdmin = state.user && state.user.is_admin;
  if (isAdmin) return openAdminAccounts();
  const multi = state.accounts.length > 1;
  const rows = state.accounts.map(a => `
    <div class="contact-item">
      <div><span class="acc-dot" style="background:${accColor(a)}"></span><b>${esc(a.email)}</b><div class="c-email">${esc(a.display_name || "")} · ${a.is_default ? "predeterminada" : ""}</div></div>
      ${multi && !a.is_default ? `<button class="btn-ghost btn btn-sm acc-default" data-accid="${a.id}" title="Establecer como cuenta principal">⭐ Hacer predeterminada</button>` : ""}
    </div>`).join("");
  const colorSection = multi ? `
    <div class="acc-color-section">
      <div class="acc-color-title">🎨 Colores de mis cuentas</div>
      ${state.accounts.map(a => `
        <div class="acc-color-row">
          <span class="acc-dot" style="background:${accColor(a)}"></span>
          <b>${esc(a.email)}</b>
          <input type="color" class="acc-color-input" data-accid="${a.id}" value="${accColor(a)}" title="Cambiar color">
        </div>`).join("")}
    </div>
    <div class="acc-color-hint">El color se guarda solo para tu usuario. Se aplica en la barra lateral, la lista y los filtros.</div>` : "";
  openModal(`
    <h2>Mis cuentas</h2>
    <div>${rows || `<div class="empty">Sin cuentas asignadas</div>`}</div>
    ${colorSection}
    <div class="admin-hint">Para agregar o modificar cuentas, contacta al administrador.</div>
    <div class="actions">
      <button class="btn-ghost btn" id="acc-close">Cerrar</button>
      <button class="btn-ghost btn" id="acc-sig">✍️ Firma personal</button>
      <button class="btn-ghost btn" id="acc-filt">📁 Filtros</button>
      ${multi ? `<button class="btn-primary btn" id="acc-colors-save">Guardar colores</button>` : ""}
    </div>`);
  document.getElementById("acc-close").onclick = closeModal;
  document.getElementById("acc-sig").onclick = openSignatureForm;
  document.getElementById("acc-filt").onclick = openFiltersManager;
  document.querySelectorAll(".acc-default").forEach(btn => {
    btn.onclick = async () => {
      const id = parseInt(btn.dataset.accid, 10);
      try {
        await api(`/accounts/${id}/default`, { method: "PUT" });
        state.accounts.forEach(a => a.is_default = a.id === id);
        renderSidebar();
        renderContent();
        toast("Cuenta predeterminada actualizada", "ok");
        openAccountsModal();
      } catch (e) { toast(e.message, "error"); }
    };
  });
  if (multi) {
    document.getElementById("acc-colors-save").onclick = async () => {
      const colors = {};
      document.querySelectorAll(".acc-color-input").forEach(inp => {
        colors[inp.dataset.accid] = inp.value;
      });
      try {
        await api("/settings/colors", { method: "PUT", body: JSON.stringify({ colors }) });
        state.userColors = colors;
        renderSidebar();
        renderContent();
        toast("Colores guardados", "ok");
      } catch (e) { toast(e.message, "error"); }
    };
  }
}

async function openAdminAccounts() {
  let list = [];
  try { list = await api("/admin/accounts"); } catch (e) { return toast(e.message, "error"); }
  const rows = list.map(a => `
    <div class="contact-item">
      <div><span class="acc-dot" style="background:${accColor(a)}"></span><b>${esc(a.email)}</b><div class="c-email">${esc(a.display_name || "")} · ${a.assigned_users.length} usuario(s)</div></div>
      <div>
        <button class="btn-ghost btn btn-sm" data-assign="${a.id}">👥 Asignar</button>
        <button class="btn-ghost btn btn-sm" data-edit="${a.id}">Editar</button>
        <button class="btn-danger btn btn-sm" data-del="${a.id}">🗑</button>
      </div>
    </div>`).join("");
  openModal(`
    <h2>Administración de cuentas</h2>
    <div class="admin-hint">Tú eliges qué cuentas de correo tiene disponible cada usuario.</div>
    <div>${rows || `<div class="empty">Sin cuentas todavía</div>`}</div>
    <div class="actions">
      <button class="btn-ghost btn" id="acc-close">Cerrar</button>
      <button class="btn-ghost btn" id="acc-sig">✍️ Firma personal</button>
      <button class="btn-ghost btn" id="acc-filt">📁 Filtros</button>
      <button class="btn-primary btn" id="acc-new">+ Nueva cuenta</button>
    </div>`);
  document.getElementById("acc-close").onclick = closeModal;
  document.getElementById("acc-sig").onclick = openSignatureForm;
  document.getElementById("acc-filt").onclick = openFiltersManager;
  document.getElementById("acc-new").onclick = () => openAccountForm();
  document.querySelectorAll("[data-edit]").forEach(b => {
    b.onclick = () => openAccountForm(parseInt(b.dataset.edit));
  });
  document.querySelectorAll("[data-assign]").forEach(b => {
    b.onclick = () => openAssignUsers(parseInt(b.dataset.assign));
  });
  document.querySelectorAll("[data-del]").forEach(b => {
    b.onclick = async () => {
      if (!confirm("¿Eliminar esta cuenta y quitar el acceso a todos los usuarios?")) return;
      try {
        await api(`/accounts/${b.dataset.del}`, { method: "DELETE" });
        toast("Cuenta eliminada", "ok");
      } catch (e) { toast(e.message, "error"); }
      openAdminAccounts();
    };
  });
}

async function openAssignUsers(accountId) {
  let users = [], list = [];
  try {
    [users, list] = await Promise.all([api("/admin/users"), api("/admin/accounts")]);
  } catch (e) { return toast(e.message, "error"); }
  const acc = list.find(a => a.id === accountId);
  if (!acc) return toast("Cuenta no encontrada", "error");
  const assigned = new Set(acc.assigned_users || []);
  const rows = users.map(u => `
    <div class="assign-row">
      <label><input type="checkbox" class="u-check" value="${u.id}" ${assigned.has(u.id) ? "checked" : ""}> <b>${esc(u.name || u.email)}</b> <span class="c-email">${esc(u.email)}</span></label>
    </div>`).join("");
  openModal(`
    <h2>Asignar usuarios · ${esc(acc.email)}</h2>
    <div>${rows || `<div class="empty">Sin usuarios en el sistema</div>`}</div>
    <div class="actions">
      <button class="btn-ghost btn" id="as-cancel">Cancelar</button>
      <button class="btn-primary btn" id="as-save">Guardar</button>
    </div>`);
  document.getElementById("as-cancel").onclick = openAdminAccounts;
  document.getElementById("as-save").onclick = async () => {
    const ids = [...document.querySelectorAll(".u-check:checked")].map(c => parseInt(c.value));
    try {
      await api(`/admin/accounts/${accountId}/assign`, { method: "POST", body: JSON.stringify({ user_ids: ids }) });
      toast("Usuarios actualizados", "ok");
    } catch (e) { toast(e.message, "error"); }
    openAdminAccounts();
  };
}

const PROVIDERS = [
  { name: "Personalizado", imap_host: "", imap_port: 993, smtp_host: "", smtp_port: 587 },
  { name: "GoDaddy (secureserver)", imap_host: "imap.secureserver.net", imap_port: 993, smtp_host: "smtpout.secureserver.net", smtp_port: 465 },
  { name: "Gmail", imap_host: "imap.gmail.com", imap_port: 993, smtp_host: "smtp.gmail.com", smtp_port: 587 },
  { name: "Outlook / Office 365", imap_host: "outlook.office365.com", imap_port: 993, smtp_host: "smtp.office365.com", smtp_port: 587 },
  { name: "Yahoo", imap_host: "imap.mail.yahoo.com", imap_port: 993, smtp_host: "smtp.mail.yahoo.com", smtp_port: 465 },
  { name: "iCloud", imap_host: "imap.mail.me.com", imap_port: 993, smtp_host: "smtp.mail.me.com", smtp_port: 587 },
  { name: "Zoho", imap_host: "imap.zoho.com", imap_port: 993, smtp_host: "smtp.zoho.com", smtp_port: 465 },
  { name: "HostGator / cPanel (mail.tu-dominio.com)", imap_host: "mail.tu-dominio.com", imap_port: 993, smtp_host: "mail.tu-dominio.com", smtp_port: 465 },
];

function providerPreset(acc) {
  if (!acc) return null;
  return PROVIDERS.find(p =>
    p.imap_host && p.imap_host === acc.imap_host && p.imap_port === acc.imap_port &&
    p.smtp_host === acc.smtp_host && p.smtp_port === acc.smtp_port);
}

function openAccountForm(accountId) {
  const acc = accountId ? state.accounts.find(a => a.id === accountId) : null;
  const v = (k, d) => acc ? (acc[k] || d) : d;
  const presetName = (providerPreset(acc) || { name: "Personalizado" }).name;
  const provOptions = PROVIDERS.map(p =>
    `<option value="${esc(p.name)}" ${p.name === presetName ? "selected" : ""}>${esc(p.name)}</option>`).join("");
  openModal(`
    <h2>${acc ? "Editar cuenta" : "Nueva cuenta"}</h2>
    <div class="modal-grid">
      <div class="field full"><label>Proveedor (rellena IMAP/SMTP automáticamente)</label><select id="f-prov">${provOptions}</select></div>
      <div class="field full"><label>Correo (remitente)</label><input id="f-email" value="${esc(v("email", ""))}" placeholder="usuario@ecc-sa.com.mx"></div>
      <div class="field full"><label>Nombre a mostrar</label><input id="f-dname" value="${esc(v("display_name", ""))}" placeholder="Nombre Apellido"></div>
      <div class="field"><label>IMAP host</label><input id="f-imap" value="${esc(v("imap_host", "imap.secureserver.net"))}"></div>
      <div class="field"><label>IMAP puerto</label><input id="f-imap-port" value="${esc(v("imap_port", "993"))}"></div>
      <div class="field"><label>SMTP host</label><input id="f-smtp" value="${esc(v("smtp_host", "smtpout.secureserver.net"))}"></div>
      <div class="field"><label>SMTP puerto</label><input id="f-smtp-port" value="${esc(v("smtp_port", "465"))}"></div>
      <div class="field full"><label>Usuario</label><input id="f-user" value="${esc(v("username", ""))}"></div>
      <div class="field full"><label>Contraseña ${acc ? "(dejar vacío = no cambiar)" : ""}</label><input id="f-pass" type="password"></div>
      <div class="field full"><label>Color de la cuenta</label><input type="color" id="f-color" value="${acc ? accColor(acc) : ACC_FALLBACK_COLORS[Math.floor(Math.random() * ACC_FALLBACK_COLORS.length)]}" style="height:38px;padding:2px;cursor:pointer"></div>
      <div class="field full"><label><input type="checkbox" id="f-default" ${acc && acc.is_default ? "checked" : ""}> Cuenta principal (remitente por defecto)</label></div>
    </div>
    <div class="actions">
      <button class="btn-ghost btn" id="f-cancel">Cancelar</button>
      <button class="btn-ghost btn" id="f-test">Probar conexión</button>
      ${acc ? `<button class="btn-danger btn" id="f-del">Eliminar</button>` : ""}
      <button class="btn-primary btn" id="f-save">Guardar</button>
    </div>`);
  document.getElementById("f-cancel").onclick = () => openAccountsModal();
  document.getElementById("f-prov").onchange = () => {
    const p = PROVIDERS.find(x => x.name === document.getElementById("f-prov").value);
    if (!p) return;
    document.getElementById("f-imap").value = p.imap_host;
    document.getElementById("f-imap-port").value = p.imap_port;
    document.getElementById("f-smtp").value = p.smtp_host;
    document.getElementById("f-smtp-port").value = p.smtp_port;
  };
  document.getElementById("f-test").onclick = async () => {
    const payload = readForm();
    if (!acc) return toast("Guarda la cuenta primero", "error");
    try {
      await api(`/accounts/${acc.id}/test`, { method: "POST" });
      toast("Conexión IMAP correcta", "ok");
    } catch (e) { toast(e.message, "error"); }
  };
  document.getElementById("f-save").onclick = async () => {
    const payload = readForm();
    try {
      if (acc) await api(`/accounts/${acc.id}`, { method: "PUT", body: JSON.stringify(payload) });
      else await api("/accounts", { method: "POST", body: JSON.stringify(payload) });
      await loadAccounts();
      closeModal();
      renderSidebar();
      toast("Cuenta guardada", "ok");
    } catch (e) { toast(e.message, "error"); }
  };
  document.getElementById("f-del").onclick = async () => {
    if (!confirm("¿Eliminar esta cuenta?")) return;
    await api(`/accounts/${acc.id}`, { method: "DELETE" });
    await loadAccounts();
    closeModal();
    renderSidebar();
    toast("Cuenta eliminada", "ok");
  };
  function readForm() {
    return {
      email: document.getElementById("f-email").value.trim(),
      display_name: document.getElementById("f-dname").value.trim(),
      imap_host: document.getElementById("f-imap").value.trim(),
      imap_port: parseInt(document.getElementById("f-imap-port").value) || 993,
      smtp_host: document.getElementById("f-smtp").value.trim(),
      smtp_port: parseInt(document.getElementById("f-smtp-port").value) || 465,
      username: document.getElementById("f-user").value.trim(),
      password: document.getElementById("f-pass").value,
      is_default: document.getElementById("f-default").checked,
      color: document.getElementById("f-color").value,
    };
  }
}

/* ============================================================ firma personal */
const SIG_FONT_SIZES = [11, 12, 13, 14, 15, 16, 18, 20];
const SIG_COLORS = ["#0B5394", "#3a3a3a", "#555555", "#888888", "#c0392b", "#27ae60", "#8e44ad", "#e67e22"];

function sanitizeSigHtml(html) {
  const doc = new DOMParser().parseFromString(html || "", "text/html");
  doc.querySelectorAll("script,iframe,object,embed,link,meta,style,form,input,button").forEach(n => n.remove());
  doc.querySelectorAll("*").forEach(n => {
    [...n.attributes].forEach(a => {
      const name = a.name.toLowerCase();
      if (name.startsWith("on") ||
          ((name === "href" || name === "src") && /^\s*javascript:/i.test(a.value))) {
        n.removeAttribute(a.name);
      }
    });
  });
  return doc.body.innerHTML;
}

function sigEditorEmpty(editor) {
  const txt = (editor.textContent || "").replace(/\u200b/g, "").trim();
  return !txt && !editor.querySelector("img,table,hr");
}

function applyFontSize(px) {
  const sel = window.getSelection();
  if (!sel || !sel.rangeCount) return;
  const range = sel.getRangeAt(0);
  if (range.collapsed) return;
  try {
    const span = document.createElement("span");
    span.style.fontSize = px + "px";
    range.surroundContents(span);
    sel.removeAllRanges();
  } catch (e) { /* selección con límites no alineados: se omite */ }
}

async function openSignatureForm() {
  let s = { display_name: "", phone: "", signature_html: "" };
  try { s = await api("/settings"); } catch (e) {}
  openModal(`
    <h2>Firma personal</h2>
    <div class="modal-grid">
      <div class="field"><label>Nombre a mostrar</label><input id="sg-name" value="${esc(s.display_name || "")}" placeholder="Nombre Apellido"></div>
      <div class="field"><label>Teléfono</label><input id="sg-phone" value="${esc(s.phone || "")}" placeholder="+52 81 0000 0000"></div>
    </div>
    <div class="field">
      <label>Editor visual (se agrega en todos los correos)</label>
      <div class="sig-toolbar">
        <button type="button" class="sig-tb" data-cmd="bold" title="Negrita"><b>B</b></button>
        <button type="button" class="sig-tb" data-cmd="italic" title="Cursiva"><i>I</i></button>
        <button type="button" class="sig-tb" data-cmd="underline" title="Subrayado"><u>U</u></button>
        <button type="button" class="sig-tb" data-cmd="removeFormat" title="Quitar formato">∅</button>
        <span class="sig-tb-sep"></span>
        <select class="sig-tb-sel" id="sg-color" title="Color de texto">
          <option value="">Color…</option>
          ${SIG_COLORS.map(c => `<option value="${c}">${c}</option>`).join("")}
        </select>
        <select class="sig-tb-sel" id="sg-size" title="Tamaño de letra">
          <option value="">Tamaño…</option>
          ${SIG_FONT_SIZES.map(n => `<option value="${n}">${n} px</option>`).join("")}
        </select>
        <span class="sig-tb-sep"></span>
        <button type="button" class="sig-tb" data-cmd="link" title="Insertar enlace">🔗</button>
        <button type="button" class="sig-tb" data-cmd="image" title="Subir imagen">🖼️</button>
        <button type="button" class="sig-tb" data-cmd="align-left" title="Alinear a la izquierda">Izq</button>
        <button type="button" class="sig-tb" data-cmd="align-center" title="Centrar">Cen</button>
        <button type="button" class="sig-tb" data-cmd="align-right" title="Alinear a la derecha">Der</button>
        <span class="sig-tb-sep"></span>
        <button type="button" class="sig-tb" id="sg-toggle" title="Cambiar a vista HTML">⟨⟩ HTML</button>
        <input type="file" id="sg-file" accept="image/png,image/jpeg,image/gif,image/webp,image/bmp" hidden>
      </div>
      <div class="sig-editor" id="sg-editor" contenteditable="true" spellcheck="false"></div>
      <textarea class="sig-source" id="sg-sig" hidden></textarea>
      <label class="sig-prev-label">La firma se guarda tal como se ve. Para insertar una imagen usa 🖼️; también puedes editar el HTML con ⟨⟩ HTML. Si la dejas vacía se usará la firma ECCSA automática.</label>
    </div>
    <div class="actions">
      <button class="btn-ghost btn" id="sg-cancel">Cancelar</button>
      <button class="btn-primary btn" id="sg-save">Guardar firma</button>
    </div>`);
  document.getElementById("sg-cancel").onclick = () => openAccountsModal();
  const editor = document.getElementById("sg-editor");
  const srcEl = document.getElementById("sg-sig");
  const toggleBtn = document.getElementById("sg-toggle");
  const fileInput = document.getElementById("sg-file");
  const initial = (s.signature_html || "").trim() || "<div><br></div>";
  editor.innerHTML = initial;
  srcEl.value = initial;

  let sourceMode = false;
  const showSource = on => {
    sourceMode = on;
    editor.hidden = on;
    srcEl.hidden = !on;
    toggleBtn.textContent = on ? "🎨 Visual" : "⟨⟩ HTML";
  };

  document.querySelectorAll(".sig-tb[data-cmd]").forEach(btn => {
    btn.addEventListener("mousedown", e => e.preventDefault());
    btn.addEventListener("click", () => {
      const cmd = btn.dataset.cmd;
      if (cmd === "link") {
        const url = prompt("URL del enlace:", "https://");
        if (url) document.execCommand("createLink", false, url);
      } else if (cmd === "image") {
        fileInput.click();
      } else if (cmd === "align-left") {
        document.execCommand("justifyLeft", false, null);
      } else if (cmd === "align-center") {
        document.execCommand("justifyCenter", false, null);
      } else if (cmd === "align-right") {
        document.execCommand("justifyRight", false, null);
      } else {
        document.execCommand(cmd, false, null);
      }
    });
  });

  document.getElementById("sg-color").addEventListener("mousedown", e => e.stopPropagation());
  document.getElementById("sg-color").addEventListener("change", e => {
    if (!e.target.value) return;
    document.execCommand("foreColor", false, e.target.value);
    e.target.value = "";
  });
  document.getElementById("sg-size").addEventListener("mousedown", e => e.stopPropagation());
  document.getElementById("sg-size").addEventListener("change", e => {
    if (!e.target.value) return;
    applyFontSize(parseInt(e.target.value, 10));
    e.target.value = "";
  });

  toggleBtn.addEventListener("click", () => {
    if (sourceMode) {
      editor.innerHTML = sanitizeSigHtml(srcEl.value) || "<div><br></div>";
    } else {
      srcEl.value = sanitizeSigHtml(editor.innerHTML);
    }
    showSource(!sourceMode);
  });

  fileInput.addEventListener("change", async () => {
    const f = fileInput.files && fileInput.files[0];
    fileInput.value = "";
    if (!f) return;
    if (f.size > 4 * 1024 * 1024) return toast("La imagen excede 4 MB", "error");
    toast("Subiendo imagen…");
    const fd = new FormData();
    fd.append("file", f);
    let res;
    try {
      res = await fetch("/api/signature/image", {
        method: "POST",
        headers: { Authorization: "Bearer " + state.token },
        body: fd,
      });
    } catch (e) {
      return toast("Error de red al subir la imagen", "error");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return toast(data.detail || "No se pudo subir la imagen", "error");
    editor.focus();
    document.execCommand("insertImage", false, data.data_uri);
    toast("Imagen agregada", "ok");
  });

  document.getElementById("sg-save").onclick = async () => {
    const html = sourceMode ? sanitizeSigHtml(srcEl.value) : sanitizeSigHtml(editor.innerHTML);
    const empty = sourceMode ? !srcEl.value.replace(/\s/g, "") : sigEditorEmpty(editor);
    const payload = {
      display_name: document.getElementById("sg-name").value.trim(),
      phone: document.getElementById("sg-phone").value.trim(),
      signature_html: empty ? "" : html,
    };
    try {
      await api("/settings", { method: "PUT", body: JSON.stringify(payload) });
      state.signature_html = payload.signature_html;
      closeModal();
      toast("Firma guardada", "ok");
    } catch (e) { toast(e.message, "error"); }
  };
}

/* ============================================================ filtros y antispam */
const FILTER_FIELDS = [
  ["from", "De (remitente)"],
  ["to", "Para"],
  ["subject", "Asunto"],
  ["body", "Contenido"],
  ["domain", "Dominio del remitente"],
];
const FILTER_ACTIONS = [
  ["mark_read", "Marcar como leído"],
  ["spam", "Marcar como spam"],
  ["delete", "Eliminar"],
  ["move", "Mover a carpeta"],
];

async function openFiltersManager() {
  let filters = [];
  try { filters = await api("/filters"); } catch (e) { return toast(e.message, "error"); }
  const rows = filters.map(f => {
    const n = (f.conditions || []).length;
    return `
    <div class="contact-item">
      <div><b>${esc(f.name || "Sin nombre")}</b>
        <div class="c-email">${f.scope === "GLOBAL" ? "Global (toda la app)" : (f.account_id ? "Cuenta " + f.account_id : "Todas mis cuentas")} · ${n} condicion(es) · ${esc(FILTER_ACTIONS.find(a => a[0] === f.action)?.[1] || f.action)} · ${f.enabled ? "activo" : "inactivo"}</div>
      </div>
      <div>
        <button class="btn-ghost btn btn-sm" data-edit="${f.id}">Editar</button>
        <button class="btn-danger btn btn-sm" data-del="${f.id}">🗑</button>
      </div>
    </div>`;
  }).join("");
  const isAdmin = state.user && state.user.is_admin;
  openModal(`
    <h2>Filtros</h2>
    <div>${rows || `<div class="empty">Sin filtros todavía</div>`}</div>
    <div class="actions">
      <button class="btn-ghost btn" id="ft-back">← Cuentas</button>
      ${isAdmin ? `<button class="btn-ghost btn" id="ft-lists">🛡 Listas antispam</button>` : ""}
      <button class="btn-primary btn" id="ft-new">+ Nuevo filtro</button>
    </div>`);
  document.getElementById("ft-back").onclick = openAccountsModal;
  document.getElementById("ft-new").onclick = () => openFilterForm();
  if (isAdmin) document.getElementById("ft-lists").onclick = openSpamListsManager;
  document.querySelectorAll("[data-edit]").forEach(b => b.onclick = () => openFilterForm(parseInt(b.dataset.edit)));
  document.querySelectorAll("[data-del]").forEach(b => b.onclick = async () => {
    if (!confirm("¿Eliminar este filtro?")) return;
    try {
      await api(`/filters/${b.dataset.del}`, { method: "DELETE" });
      toast("Filtro eliminado", "ok");
    } catch (e) { toast(e.message, "error"); }
    openFiltersManager();
  });
}

function openFilterForm(filterId, prefill) {
  const f = filterId ? null : null;
  let cur = null;
  if (filterId) {
    api("/filters").then(list => {
      cur = list.find(x => x.id === filterId);
      render(cur);
    }).catch(e => toast(e.message, "error"));
  } else {
    render(Object.assign({ scope: "ACCOUNT", account_id: state.currentAccountId, name: "", conditions: [{ field: "from", op: "contains", value: "" }], action: "spam", action_folder: "", enabled: true, order_no: 0 }, prefill || {}));
  }
  function render(base) {
    const accOpts = state.accounts.map(a => `<option value="${a.id}" ${a.id === base.account_id ? "selected" : ""}>${esc(a.email)}</option>`).join("");
    const condRows = (base.conditions || []).map((c, i) => `
      <div class="cond-row">
        <select class="c-field" data-i="${i}">${FILTER_FIELDS.map(([v, l]) => `<option value="${v}" ${c.field === v ? "selected" : ""}>${l}</option>`).join("")}</select>
        <select class="c-op" data-i="${i}">
          <option value="contains" ${c.op === "contains" ? "selected" : ""}>contiene</option>
          <option value="equals" ${c.op === "equals" ? "selected" : ""}>es igual a</option>
        </select>
        <input class="c-val" data-i="${i}" value="${esc(c.value || "")}" placeholder="texto…">
        <button class="btn-danger btn btn-sm c-del" data-i="${i}">−</button>
      </div>`).join("");
    openModal(`
      <h2>${filterId ? "Editar filtro" : "Nuevo filtro"}</h2>
      <div class="field"><label>Nombre</label><input id="cf-name" value="${esc(base.name || "")}" placeholder="Ej. Facturas del proveedor"></div>
      <div class="field"><label>Alcance</label><select id="cf-scope">
        <option value="ACCOUNT" ${base.scope === "ACCOUNT" ? "selected" : ""}>Cuenta</option>
        ${state.user && state.user.is_admin ? `<option value="GLOBAL" ${base.scope === "GLOBAL" ? "selected" : ""}>Global (toda la app)</option>` : ""}
      </select></div>
      <div class="field" id="cf-acc-wrap"><label>Cuenta</label><select id="cf-acc">${accOpts}</select></div>
      <div class="field"><label>Condiciones (todas deben cumplirse)</label><div id="cf-conds">${condRows}</div>
        <button class="btn-ghost btn btn-sm" id="cf-add">+ Agregar condición</button></div>
      <div class="field"><label>Acción</label><select id="cf-action">${FILTER_ACTIONS.map(([v, l]) => `<option value="${v}" ${base.action === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>
      <div class="field" id="cf-folder-wrap"><label>Carpeta destino</label><input id="cf-folder" value="${esc(base.action_folder || "")}" placeholder="Ej. INBOX/Clientes"></div>
      <div class="field"><label><input type="checkbox" id="cf-enabled" ${base.enabled ? "checked" : ""}> Activo</label></div>
      <div class="actions">
        <button class="btn-ghost btn" id="cf-cancel">Cancelar</button>
        <button class="btn-primary btn" id="cf-save">Guardar</button>
      </div>`);
    const scopeEl = document.getElementById("cf-scope");
    const syncScope = () => {
      document.getElementById("cf-acc-wrap").style.display = scopeEl.value === "ACCOUNT" ? "" : "none";
    };
    scopeEl.onchange = syncScope;
    syncScope();
    const syncAction = () => {
      document.getElementById("cf-folder-wrap").style.display = document.getElementById("cf-action").value === "move" ? "" : "none";
    };
    document.getElementById("cf-action").onchange = syncAction;
    syncAction();
    document.getElementById("cf-add").onclick = () => {
      const wrap = document.getElementById("cf-conds");
      const i = wrap.querySelectorAll(".cond-row").length;
      wrap.insertAdjacentHTML("beforeend", `
        <div class="cond-row">
          <select class="c-field" data-i="${i}">${FILTER_FIELDS.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select>
          <select class="c-op" data-i="${i}">
            <option value="contains">contiene</option>
            <option value="equals">es igual a</option>
          </select>
          <input class="c-val" data-i="${i}" placeholder="texto…">
          <button class="btn-danger btn btn-sm c-del" data-i="${i}">−</button>
        </div>`);
    };
    document.getElementById("cf-conds").addEventListener("click", e => {
      if (e.target.classList.contains("c-del")) e.target.closest(".cond-row").remove();
    });
    document.getElementById("cf-cancel").onclick = openFiltersManager;
    document.getElementById("cf-save").onclick = async () => {
      const conds = [...document.querySelectorAll(".cond-row")].map(r => ({
        field: r.querySelector(".c-field").value,
        op: r.querySelector(".c-op").value,
        value: r.querySelector(".c-val").value.trim(),
      })).filter(c => c.value);
      const payload = {
        scope: document.getElementById("cf-scope").value,
        account_id: document.getElementById("cf-scope").value === "ACCOUNT" ? parseInt(document.getElementById("cf-acc").value) : null,
        name: document.getElementById("cf-name").value.trim(),
        conditions: conds,
        action: document.getElementById("cf-action").value,
        action_folder: document.getElementById("cf-folder").value.trim(),
        enabled: document.getElementById("cf-enabled").checked,
        order_no: 0,
      };
      try {
        if (filterId) await api(`/filters/${filterId}`, { method: "PUT", body: JSON.stringify(payload) });
        else await api("/filters", { method: "POST", body: JSON.stringify(payload) });
        toast("Filtro guardado", "ok");
        closeModal();
      } catch (e) { toast(e.message, "error"); }
    };
  }
}

async function openSpamListsManager() {
  let lists = [];
  try { lists = await api("/spam-lists"); } catch (e) { return toast(e.message, "error"); }
  const rows = lists.map(l => `
    <div class="contact-item">
      <div><b>${esc(l.name)}</b><div class="c-email">${esc(l.zone)} · ${l.enabled ? "activa" : "inactiva"} · prioridad ${l.priority}</div></div>
      <div>
        <button class="btn-ghost btn btn-sm" data-edit="${l.id}">Editar</button>
        <button class="btn-danger btn btn-sm" data-del="${l.id}">🗑</button>
      </div>
    </div>`).join("");
  openModal(`
    <h2>Listas antispam (DNSBL)</h2>
    <div>${rows || `<div class="empty">Sin listas</div>`}</div>
    <div class="actions">
      <button class="btn-ghost btn" id="sl-back">← Filtros</button>
      <button class="btn-primary btn" id="sl-new">+ Nueva lista</button>
    </div>`);
  document.getElementById("sl-back").onclick = openFiltersManager;
  document.getElementById("sl-new").onclick = () => openSpamListForm();
  document.querySelectorAll("[data-edit]").forEach(b => b.onclick = () => openSpamListForm(parseInt(b.dataset.edit)));
  document.querySelectorAll("[data-del]").forEach(b => b.onclick = async () => {
    if (!confirm("¿Eliminar esta lista?")) return;
    try {
      await api(`/spam-lists/${b.dataset.del}`, { method: "DELETE" });
      toast("Lista eliminada", "ok");
    } catch (e) { toast(e.message, "error"); }
    openSpamListsManager();
  });
}

function openSpamListForm(listId) {
  api("/spam-lists").then(lists => {
    const l = lists.find(x => x.id === listId);
    render(l || { name: "", zone: "zen.spamhaus.org", list_type: "DNSBL", enabled: true, priority: 0 });
  }).catch(e => toast(e.message, "error"));
  function render(base) {
    openModal(`
      <h2>${listId ? "Editar lista" : "Nueva lista"}</h2>
      <div class="field"><label>Nombre</label><input id="sl-name" value="${esc(base.name || "")}"></div>
      <div class="field"><label>Zona DNSBL</label><input id="sl-zone" value="${esc(base.zone || "")}" placeholder="ej. zen.spamhaus.org"></div>
      <div class="field"><label>Prioridad (0 = primera)</label><input id="sl-pri" type="number" value="${base.priority || 0}"></div>
      <div class="field"><label><input type="checkbox" id="sl-enabled" ${base.enabled ? "checked" : ""}> Activa</label></div>
      <div class="actions">
        <button class="btn-ghost btn" id="sl-cancel">Cancelar</button>
        <button class="btn-primary btn" id="sl-save">Guardar</button>
      </div>`);
    document.getElementById("sl-cancel").onclick = openSpamListsManager;
    document.getElementById("sl-save").onclick = async () => {
      const payload = {
        name: document.getElementById("sl-name").value.trim(),
        zone: document.getElementById("sl-zone").value.trim(),
        list_type: "DNSBL",
        enabled: document.getElementById("sl-enabled").checked,
        priority: parseInt(document.getElementById("sl-pri").value) || 0,
      };
      try {
        if (listId) await api(`/spam-lists/${listId}`, { method: "PUT", body: JSON.stringify(payload) });
        else await api("/spam-lists", { method: "POST", body: JSON.stringify(payload) });
        toast("Lista guardada", "ok");
        openSpamListsManager();
      } catch (e) { toast(e.message, "error"); }
    };
  }
}

/* ============================================================ notifications */
let notifTimer = null;

async function initPushNotifications() {
  try {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;
    const cfg = await api("/push/config");
    if (!cfg || !cfg.vapid_public_key) return;
    const reg = await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      if (Notification && Notification.permission === "default") {
        Notification.requestPermission();
      }
      if (Notification && Notification.permission !== "granted") return;
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(cfg.vapid_public_key),
      });
    }
    if (sub) {
      const j = sub.toJSON();
      await api("/push/subscribe", {
        method: "POST",
        body: JSON.stringify({ endpoint: j.endpoint, p256dh: j.keys.p256dh, auth: j.keys.auth }),
      });
    }
  } catch (e) {}
}

function urlBase64ToUint8Array(b64) {
  const pad = b64.replace(/=+$/, "");
  const raw = atob(pad.replace(/-/g, "+").replace(/_/g, "/"));
  const arr = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
  return arr;
}

function startNotifications() {
  if (notifTimer) clearInterval(notifTimer);
  const tick = async () => {
    try {
      const res = await api("/notifications");
      const total = res.reduce((n, r) => n + (r.unread || 0), 0);
      const badge = document.getElementById("notif-badge");
      if (badge && !state.unreadOnly) badge.textContent = total ? total : "";
    } catch (e) {}
    try {
      await loadUnreadCounts();
    } catch (e) {}
    try {
      const res = await api("/notifications/new");
      const items = res.items || [];
      if (!state.notifiedSeeded) {
        items.forEach(it => state.notified.add(it.account_id + ":" + it.uid));
        state.notifiedSeeded = true;
        return;
      }
      items.forEach(it => {
        const k = it.account_id + ":" + it.uid;
        if (!state.notified.has(k)) {
          state.notified.add(k);
          showMailNotification(it);
        }
      });
      if (state.notified.size > 300) {
        state.notified = new Set([...state.notified].slice(-200));
      }
    } catch (e) {}
  };
  tick();
  notifTimer = setInterval(tick, 60000);
}

function showMailNotification(item) {
  const stack = document.getElementById("notif-stack");
  if (!stack) return;
  const card = document.createElement("div");
  card.className = "notif-card";
  const fromName = item.from_name || item.from_email || "";
  card.innerHTML = `
    <div class="notif-head">
      <span class="notif-account">📬 ${esc(item.email)}</span>
      <button class="notif-close" title="Cerrar">✕</button>
    </div>
    <div class="notif-from">${esc(fromName)} &lt;${esc(item.from_email)}&gt;</div>
    <div class="notif-subject">${esc(item.subject)}</div>
    <div class="notif-meta">${esc(item.date)}</div>
    <div class="notif-preview">${esc(item.preview)}</div>`;
  card.querySelector(".notif-close").onclick = e => {
    e.stopPropagation();
    card.remove();
  };
  card.onclick = async () => {
    card.remove();
    try {
      await openAccountInbox(item.account_id, item.uid);
    } catch (e) { toast(e.message, "error"); }
  };
  stack.appendChild(card);
  setTimeout(() => card.remove(), 20000);
  while (stack.children.length > 5) stack.firstChild.remove();
}

async function openAccountInbox(accountId, uid) {
  state.unified = false;
  if (accountId !== state.currentAccountId || state.currentFolder !== "INBOX") {
    state.currentAccountId = accountId;
    state.currentFolder = "INBOX";
    state.page = 1;
    state.q = "";
    state.unreadOnly = false;
    const fa = state.foldersByAccount[accountId] || { folders: [], delimiter: "/" };
    state.folders = fa.folders;
    state.folderDelimiter = fa.delimiter;
    state.expandedFolders = state.expandedByAccount[accountId] || {};
    closeDrawer();
    renderSidebar();
    await loadMessages();
    renderContent();
  }
  await openMessage(String(uid));
}

/* ============================================================ init */
// Error handlers para debugging en pantalla
window.addEventListener("error", (e) => {
  const s = document.getElementById("splash");
  if (s) s.innerHTML = '<div style="color:#e04b3a;padding:20px;font-family:monospace;font-size:12px;max-width:600px;margin:auto;text-align:left"><b>Error JS:</b><br>' + (e.message || e.error?.message || "desconocido") + '<br><br>Archivo: ' + (e.filename || "?") + ':' + (e.lineno || "?") + '</div>';
});
window.addEventListener("unhandledrejection", (e) => {
  const s = document.getElementById("splash");
  if (s) s.innerHTML = '<div style="color:#e04b3a;padding:20px;font-family:monospace;font-size:12px;max-width:600px;margin:auto;text-align:left"><b>Error promesa:</b><br>' + (e.reason?.message || e.reason || "desconocido") + '</div>';
});
(async function init() {
  applyTheme(state.theme);
  applyWallpaper();
  try { const d = await api("/loading-phrases"); state.splashPhrases = d.phrases || []; } catch(_){}
  if (state.splashPhrases.length) {
    const sp = document.getElementById("splash-phrase");
    if (sp) sp.textContent = state.splashPhrases[Math.floor(Math.random() * state.splashPhrases.length)];
  }
  if (!state.token) {
    renderLogin();
    hideSplash();
    return;
  }
  showLoading("Cargando HUBMail…");
  try {
    state.user = await api("/auth/me");
    await boot();
  } catch (e) {
    renderLogin();
  } finally {
    hideLoading();
    hideSplash();
  }
})();