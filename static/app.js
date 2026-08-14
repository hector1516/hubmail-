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
  composeAttachments: [],
  selected: new Set(),
};

const app = document.getElementById("app");
const modalRoot = document.getElementById("modal-root");
const toastRoot = document.getElementById("toast-root");

function showLoading(text = "Cargando…") {
  const o = document.getElementById("loading-overlay");
  const t = document.getElementById("loading-text");
  if (t) t.textContent = text;
  if (o) o.classList.remove("hidden");
}

function hideLoading() {
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

/* ============================================================ login */
function renderLogin() {
  app.innerHTML = `
    <div class="login-wrap">
      <div class="login-card">
        <h1>HUBMail</h1>
        <div class="sub">Correo corporativo ECCSA</div>
        <div class="field"><label>Correo</label><input id="lg-email" type="email" placeholder="usuario@ecc-sa.com.mx" autocomplete="username"></div>
        <div class="field"><label>Contraseña</label><input id="lg-pass" type="password" placeholder="••••••••" autocomplete="current-password"></div>
        <button class="btn btn-primary" id="lg-btn" style="width:100%;padding:11px">Iniciar sesión</button>
      </div>
    </div>`;
  const doLogin = async () => {
    const email = document.getElementById("lg-email").value.trim();
    const password = document.getElementById("lg-pass").value;
    if (!email || !password) return toast("Ingresa correo y contraseña", "error");
    showLoading("Iniciando sesión…");
    try {
      const data = await api("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
      state.token = data.token;
      state.user = data.user;
      localStorage.setItem("hubmail_token", data.token);
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
  localStorage.removeItem("hubmail_token");
  renderLogin();
}

/* ============================================================ shell */
async function boot() {
  try {
    await loadAccounts();
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
    await loadMessages();
    renderShell();
    startNotifications();
    startFolderRefresh();
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
  } finally {
    hideLoading();
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

async function loadMessages() {
  if (!state.currentAccountId) return;
  showLoading("Cargando correos…");
  try {
    state.selected.clear();
    const qs = `?folder=${encodeURIComponent(state.currentFolder)}&page=${state.page}&q=${encodeURIComponent(state.q)}&unread_only=${state.unreadOnly}`;
    const data = await api(`/accounts/${state.currentAccountId}/messages${qs}`);
    state.messages = data.messages;
    state.total = data.total;
    state.lastSync = data.last_sync || null;
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
    return `
      <div class="msg-item ${m.unread ? "unread" : ""} ${sel ? "selected" : ""}" data-id="${esc(m.id)}">
        <input type="checkbox" class="msg-check" data-id="${esc(m.id)}" ${sel ? "checked" : ""}>
        <div class="msg-main">
          <div class="row1">
            <div class="from">${esc(sender)}</div>
            <div class="date">${esc(m.date)}</div>
          </div>
          <div class="subject">${m.flagged ? "★ " : ""}${esc(m.subject)}</div>
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
  document.querySelectorAll("#message-list .msg-item").forEach(el => {
    const id = el.dataset.id;
    el.onclick = () => {
      clearTimeout(el._t);
      el._t = setTimeout(() => openMessage(id), 220);
    };
    el.ondblclick = (e) => {
      e.preventDefault();
      if (e.target.classList.contains("msg-check")) return;
      clearTimeout(el._t);
      openMessageModal(id);
    };
  });
  document.querySelectorAll(".msg-check").forEach(cb => {
    cb.onclick = (e) => {
      e.stopPropagation();
      const id = cb.dataset.id;
      if (cb.checked) state.selected.add(id);
      else state.selected.delete(id);
      cb.closest(".msg-item").classList.toggle("selected", cb.checked);
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
  if (refreshing || document.hidden || !state.currentAccountId || !state.currentFolder) return;
  if (modalRoot.querySelector(".modal")) return;
  refreshing = true;
  api(`/accounts/${state.currentAccountId}/messages?folder=${encodeURIComponent(state.currentFolder)}&page=${state.page}&q=${encodeURIComponent(state.q)}&unread_only=${state.unreadOnly}`)
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
      const pager = document.querySelector(".pager");
      if (pager) { pager.innerHTML = pagerHtml(); bindPager(); }
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

function renderShell() {
  app.innerHTML = `
    <div class="shell">
      <header>
        <button class="icon-btn" id="btn-menu" title="Menú">☰</button>
        <div class="brand">HUBMail</div>
        <div class="header-right">
          <button class="icon-btn" id="btn-notif" title="No leídos">📬<span class="badge" id="notif-badge"></span></button>
          <button class="icon-btn btn-primary" id="btn-compose">✉️ Redactar</button>
          <button class="icon-btn" id="btn-accounts" title="Cuentas y firma">⚙️</button>
          <span class="user-name">${esc(state.user?.name || state.user?.email || "")}</span>
          <button class="icon-btn" id="btn-logout" title="Salir">⏻</button>
        </div>
      </header>
      <div class="body">
        <aside id="sidebar"></aside>
        <main id="content"></main>
      </div>
    </div>`;

  document.getElementById("btn-menu").onclick = () => document.getElementById("sidebar").classList.toggle("open");
  document.getElementById("btn-compose").onclick = () => openCompose();
  document.getElementById("btn-accounts").onclick = () => openAccountsModal();
  document.getElementById("btn-logout").onclick = logout;
  document.getElementById("btn-notif").onclick = () => {
    state.unreadOnly = !state.unreadOnly;
    state.page = 1;
    loadMessages().then(renderContent).catch(e => toast(e.message, "error"));
  };

  renderSidebar();
  renderContent();
  if (window.innerWidth <= 820) document.getElementById("sidebar").classList.add("open");
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

function renderFolderTree(node, depth, expanded, accId) {
  let html = "";
  const names = Object.keys(node.children).sort((a, b) =>
    node.children[a].name.toLowerCase().localeCompare(node.children[b].name.toLowerCase()));
  for (const n of names) {
    const child = node.children[n];
    const hasKids = Object.keys(child.children).length > 0;
    const isActive = state.currentAccountId === accId && state.currentFolder === child.full;
    const pad = 14 + depth * 16;
    const up = child.full.toUpperCase();
    const icon = hasKids ? (expanded[child.full] ? "📂" : "📁") : (up === "INBOX" ? "📥" : "📄");
    if (!hasKids) {
      html += `<li class="fitem ${isActive ? "active" : ""}" data-folder="${esc(child.full)}" style="padding-left:${pad}px"><span class="fi-ico">${icon}</span><span class="fi-name">${esc(child.name)}</span></li>`;
    } else {
      const open = !!expanded[child.full];
      html += `<li class="fitem fnode ${isActive ? "active" : ""}" style="padding-left:${pad - 6}px">
        <span class="caret" data-caret="${esc(child.full)}">${open ? "▾" : "▸"}</span>
        <span class="fi-ico">${icon}</span>
        <span data-folder="${esc(child.full)}">${esc(child.name)}</span>
      </li>`;
      if (open) {
        html += `<ul class="folders">${renderFolderTree(child, depth + 1, expanded, accId)}</ul>`;
      }
    }
  }
  return html;
}

function renderSidebar() {
  const sb = document.getElementById("sidebar");
  const list = state.accounts.map(acc => {
    const fa = state.foldersByAccount[acc.id] || { folders: [], delimiter: "/" };
    const expanded = state.expandedByAccount[acc.id] || {};
    const tree = buildFolderTree(fa.folders, fa.delimiter);
    const show = renderFolderTree(tree, 0, expanded, acc.id);
    const isCurrent = state.currentAccountId === acc.id;
    return `
      <div class="account-block" data-acc="${acc.id}">
        <div class="account-head ${isCurrent ? "current" : ""}" data-acc="${acc.id}" title="Cuentas y firma">
          <div>${esc(acc.display_name || acc.email)}<br><small>${esc(acc.email)}${fa.folders.length ? ` · ${fa.folders.length} carpetas` : ""}${acc.shared ? " · <span class=\"shared-badge\">Compartida</span>" : ""}</small></div>
        </div>
        ${show ? `<div class="sec-title">Carpetas</div><ul class="folders" data-acc="${acc.id}">${show}</ul>` : ""}
      </div>`;
  }).join("");

  sb.innerHTML = `
    <div class="side-actions">
      <button class="btn-ghost btn" id="sb-compose">✉️ Redactar</button>
      <button class="btn-ghost btn" id="sb-contacts">👥 Contactos</button>
      <button class="btn-ghost btn" id="sb-accounts">⚙️ Cuentas y firma</button>
    </div>
    ${list}`;

  document.getElementById("sb-compose").onclick = () => { sb.classList.remove("open"); openCompose(); };
  document.getElementById("sb-contacts").onclick = () => { sb.classList.remove("open"); openContactsManager(); };
  document.getElementById("sb-accounts").onclick = () => { sb.classList.remove("open"); openAccountsModal(); };

  sb.querySelectorAll(".account-head").forEach(el => {
    el.onclick = async () => {
      const id = parseInt(el.dataset.acc);
      if (id !== state.currentAccountId) {
        state.currentAccountId = id;
        state.currentFolder = "INBOX";
        state.page = 1;
        state.q = "";
        state.unreadOnly = false;
        const fa = state.foldersByAccount[id] || { folders: [], delimiter: "/" };
        state.folders = fa.folders;
        state.folderDelimiter = fa.delimiter;
        state.expandedFolders = state.expandedByAccount[id] || {};
        try {
          await loadMessages();
          renderSidebar();
          renderContent();
        } catch (e) { toast(e.message, "error"); }
      }
    };
  });
  sb.querySelectorAll('[data-folder]').forEach(el => {
    el.onclick = async (e) => {
      e.stopPropagation();
      const accId = parseInt(el.closest("[data-acc]").dataset.acc);
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
      sb.classList.remove("open");
      try {
        await loadMessages();
        renderSidebar();
        renderContent();
      } catch (e) { toast(e.message, "error"); }
    };
  });
  sb.querySelectorAll('[data-caret]').forEach(el => {
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
}

function renderContent() {
  const content = document.getElementById("content");
  const totalUnread = state.messages.reduce((n, m) => n + (m.unread ? 1 : 0), 0);
  document.getElementById("notif-badge").textContent = state.unreadOnly ? "✓" : (totalUnread ? totalUnread : "");

  const pages = Math.max(1, Math.ceil(state.total / 25));
  const msgs = messagesHtml();

  content.innerHTML = `
    <div id="list-pane">
      <div class="list-toolbar">
        <div class="folder-title">${esc(state.currentFolder)} ${state.unreadOnly ? "(no leídos)" : ""}</div>
        <div class="last-update">${state.lastSync ? "Actualizado " + esc(state.lastSync) : "Sin sincronizar"}</div>
        <label class="sel-all" title="Seleccionar todos"><input type="checkbox" id="sel-all"></label>
        <input id="search-box" placeholder="Buscar..." value="${esc(state.q)}">
        <button class="btn-ghost btn btn-sm" id="btn-refresh">⟳</button>
        <button class="btn-ghost btn btn-sm" id="btn-unread">${state.unreadOnly ? "Todo" : "No leídos"}</button>
        <div class="bulk-bar" id="bulk-bar">
          <button class="btn-ghost btn btn-sm" id="btn-sel-all">☑ Todo</button>
          <button class="btn-danger btn btn-sm" id="btn-del-sel">🗑 Eliminar (<span id="sel-count">0</span>)</button>
          <button class="btn-ghost btn btn-sm" id="btn-clear-sel">Cancelar</button>
        </div>
      </div>
      <div id="message-list">${msgs}</div>
      <div class="pager">
        <button class="btn-ghost btn btn-sm" id="btn-prev" ${state.page <= 1 ? "disabled" : ""}>← Anterior</button>
        <span>Página ${state.page} de ${pages} · ${state.total} mensajes</span>
        <button class="btn-ghost btn btn-sm" id="btn-next" ${state.page >= pages ? "disabled" : ""}>Siguiente →</button>
      </div>
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
  const selAll = document.getElementById("sel-all");
  selAll.onchange = () => {
    if (selAll.checked) state.messages.forEach(m => state.selected.add(m.id));
    else state.messages.forEach(m => state.selected.delete(m.id));
    renderContent();
  };
  syncSelectAll();
  document.getElementById("btn-refresh").onclick = () => {
    Promise.all([loadMessages(), loadFolders()]).then(() => { renderContent(); renderSidebar(); }).catch(e => toast(e.message, "error"));
  };
  document.getElementById("btn-unread").onclick = () => {
    state.unreadOnly = !state.unreadOnly;
    state.page = 1;
    loadMessages().then(renderContent).catch(e => toast(e.message, "error"));
  };
  document.getElementById("btn-prev").onclick = () => { if (state.page > 1) { state.page--; loadMessages().then(renderContent); } };
  document.getElementById("btn-next").onclick = () => { if (state.page < pages) { state.page++; loadMessages().then(renderContent); } };

  bindMessageList();
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
  updateBulkBar();

  const dp = document.getElementById("detail-pane");
  if (state.currentMsgId) {
    loadMessageDetail(state.currentMsgId).then(m => {
      if (document.getElementById("detail-pane")) renderDetail(m);
    }).catch(() => {});
  } else {
    dp.innerHTML = `<div class="empty" style="margin-top:80px">Selecciona un mensaje para leerlo</div>`;
  }
}

function updateBulkBar() {
  const bar = document.getElementById("bulk-bar");
  const count = document.getElementById("sel-count");
  if (bar) bar.style.display = state.selected.size ? "flex" : "none";
  if (count) count.textContent = state.selected.size;
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
  state.currentMsgId = id;
  showLoading("Cargando mensaje…");
  try {
    const m = await loadMessageDetail(id);
    renderDetail(m);
    if (m.unread) {
      api(`/accounts/${state.currentAccountId}/messages/${encodeURIComponent(id)}?folder=${encodeURIComponent(state.currentFolder)}&action=read`, { method: "PATCH" }).catch(() => {});
      state.messages.forEach(x => { if (x.id === id) x.unread = false; });
      renderContent();
    }
  } catch (e) {
    toast(e.message, "error");
  } finally {
    hideLoading();
  }
}

async function loadMessageDetail(id) {
  return api(`/accounts/${state.currentAccountId}/messages/${encodeURIComponent(id)}?folder=${encodeURIComponent(state.currentFolder)}`);
}

function detailHtml(m) {
  const from = m.from[0];
  const sender = from ? `${esc(from.name || "")} &lt;${esc(from.email)}&gt;` : "";
  const to = m.to.map(t => `<span class="chip">${esc(t.name || t.email)}</span>`).join("");
  const cc = m.cc.length ? `<div class="detail-meta">CC: ${m.cc.map(t => esc(t.name || t.email)).join(", ")}</div>` : "";
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

  return `
    <div class="detail-toolbar">
      <button class="btn-ghost btn btn-sm" id="d-back">←</button>
      <button class="btn-ghost btn btn-sm" id="d-reply">↩ Responder</button>
      <button class="btn-ghost btn btn-sm" id="d-fwd">↪ Reenviar</button>
      <button class="btn-ghost btn btn-sm" id="d-flag">${m.flagged ? "★" : "☆"}</button>
      <span class="spacer"></span>
      <button class="btn-danger btn btn-sm" id="d-del">🗑</button>
    </div>
    <div class="detail-body">
      <div class="detail-subject">${esc(m.subject)}</div>
      <div class="detail-from">${sender}</div>
      <div class="detail-meta">Para: ${to}</div>
      ${cc}
      <div class="detail-meta">Fecha: ${esc(m.date)}</div>
      ${atts}
      <iframe class="body-frame" sandbox="" srcdoc="${esc(bodyHtml || "")}"></iframe>
    </div>`;
}

function renderDetail(m) {
  const dp = document.getElementById("detail-pane");
  dp.innerHTML = detailHtml(m);
  dp.classList.add("open");
  bindDetailActions(m);
}

function bindDetailActions(m) {
  const isModal = !!modalRoot.querySelector(".modal");
  const dp = document.getElementById("detail-pane");
  document.getElementById("d-back").onclick = () => {
    state.currentMsgId = null;
    if (isModal) closeModal();
    else if (dp) dp.classList.remove("open");
  };
  document.getElementById("d-del").onclick = async () => {
    if (!confirm("¿Eliminar este mensaje?")) return;
    await api(`/accounts/${state.currentAccountId}/messages/${encodeURIComponent(m.id)}?folder=${encodeURIComponent(state.currentFolder)}&action=delete`, { method: "PATCH" }).catch(e => toast(e.message, "error"));
    state.currentMsgId = null;
    await loadMessages();
    renderContent();
    if (isModal) closeModal();
    toast("Mensaje eliminado", "ok");
  };
  document.getElementById("d-flag").onclick = async () => {
    await api(`/accounts/${state.currentAccountId}/messages/${encodeURIComponent(m.id)}?folder=${encodeURIComponent(state.currentFolder)}&action=${m.flagged ? "unflag" : "flag"}`, { method: "PATCH" }).catch(() => {});
    m.flagged = !m.flagged;
    document.getElementById("d-flag").textContent = m.flagged ? "★" : "☆";
  };
  document.getElementById("d-reply").onclick = () => {
    const f = m.from[0];
    openCompose({ to: [f && f.email], subject: m.subject.startsWith("Re:") ? m.subject : "Re: " + m.subject, reply_to: m.message_id });
  };
  document.getElementById("d-fwd").onclick = () => {
    openCompose({ subject: m.subject.startsWith("Fwd:") ? m.subject : "Fwd: " + m.subject });
  };
}

async function openMessageModal(id) {
  const dp = document.getElementById("detail-pane");
  if (dp) dp.classList.remove("open");
  state.currentMsgId = null;
  showLoading("Cargando mensaje…");
  try {
    const m = await loadMessageDetail(id);
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
function openCompose(prefill = {}) {
  const accOptions = state.accounts.map(a =>
    `<option value="${a.id}" ${a.id === state.currentAccountId ? "selected" : ""}>${esc(a.email)}</option>`).join("");
  state.composeAttachments = [];
  openModal(`
    <h2>Nuevo mensaje</h2>
    <div class="compose-row"><label>De:</label><select id="c-from">${accOptions}</select></div>
    <div class="compose-row"><label>Para:</label><input id="c-to" value="${esc((prefill.to || []).join(", "))}" placeholder="correo@dominio.com"></div>
    <div class="compose-row"><label>CC:</label><input id="c-cc" placeholder="opcional"></div>
    <div class="compose-row"><label>Asunto:</label><input id="c-subject" value="${esc(prefill.subject || "")}"></div>
    <div class="compose-row"><label>Adj:</label><input type="file" id="c-files" multiple></div>
    <div class="attach-list" id="c-attach-list"></div>
    <textarea id="compose-body" placeholder="Escribe tu mensaje..."></textarea>
    <div class="actions">
      <button class="btn-ghost btn" id="c-contacts">👥 Contactos</button>
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
  const bodyText = document.getElementById("compose-body").value;
  const accountId = parseInt(document.getElementById("c-from").value);
  if (!to.length) return toast("Indica al menos un destinatario", "error");
  const bodyHtml = bodyText.split("\n").map(l => esc(l)).join("<br>");
  const btn = document.getElementById("c-send");
  btn.disabled = true;
  btn.textContent = "Enviando...";
  showLoading("Enviando correo…");
  try {
    await api(`/accounts/${accountId}/send`, {
      method: "POST",
      body: JSON.stringify({ to, cc, subject, body_html: bodyHtml, attachments: state.composeAttachments }),
    });
    closeModal();
    toast("Correo enviado", "ok");
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
  const usersHtml = data.users.map(u =>
    `<div class="contact-item">
      <div><b>${esc(u.name)}</b><div class="c-email">${esc(u.email)}</div></div>
      <button class="btn-ghost btn btn-sm" data-email="${esc(u.email)}">Usar</button>
    </div>`).join("") || `<div class="empty">Sin usuarios activos</div>`;
  const contactsHtml = data.contacts.map(c =>
    `<div class="contact-item">
      <div><b>${esc(c.name)}</b><div class="c-email">${esc(c.email)}</div></div>
      <div>
        ${pickMode ? `<button class="btn-ghost btn btn-sm" data-email="${esc(c.email)}">Usar</button>` : ""}
        <button class="btn-ghost btn btn-sm" data-edit="${c.id}" title="Editar">✎</button>
        <button class="btn-danger btn btn-sm" data-del="${c.id}" title="Eliminar">✕</button>
      </div>
    </div>`).join("") || `<div class="empty">Sin contactos recopilados</div>`;

  openModal(`
    <h2>Contactos</h2>
    <h3 class="sec-title">Usuarios ECCSA</h3>
    ${usersHtml}
    <h3 class="sec-title">Contactos recopilados</h3>
    ${contactsHtml}
    <div class="actions">
      <button class="btn-ghost btn" id="ct-new">+ Agregar</button>
      <span class="spacer"></span>
      <button class="btn-ghost btn" id="ct-close">Cerrar</button>
    </div>`);

  document.getElementById("ct-close").onclick = closeModal;
  document.getElementById("ct-new").onclick = () => openContactForm(null, pickMode);
  document.querySelectorAll("[data-email]").forEach(b => {
    b.onclick = () => { closeModal(); useContact(b.dataset.email); };
  });
  document.querySelectorAll("[data-edit]").forEach(b => {
    b.onclick = () => openContactForm(data.contacts.find(x => x.id === parseInt(b.dataset.edit)), pickMode);
  });
  document.querySelectorAll("[data-del]").forEach(b => {
    b.onclick = async () => {
      if (!confirm("¿Eliminar este contacto recopilado?")) return;
      try {
        await api(`/contacts/${b.dataset.del}`, { method: "DELETE" });
        toast("Contacto eliminado", "ok");
      } catch (e) { toast(e.message, "error"); }
      openContactsManager(pickMode);
    };
  });
}

function openContactForm(c, pickMode) {
  openModal(`
    <h2>${c ? "Editar contacto" : "Nuevo contacto"}</h2>
    <div class="field"><label>Nombre</label><input id="cf-name" value="${esc(c?.name || "")}"></div>
    <div class="field"><label>Email</label><input id="cf-email" value="${esc(c?.email || "")}"></div>
    <div class="field"><label>Teléfono</label><input id="cf-phone" value="${esc(c?.phone || "")}"></div>
    <div class="field"><label>Notas</label><textarea id="cf-notes">${esc(c?.notes || "")}</textarea></div>
    <div class="actions">
      <button class="btn-ghost btn" id="cf-cancel">Cancelar</button>
      <button class="btn-primary btn" id="cf-save">Guardar</button>
    </div>`);
  document.getElementById("cf-cancel").onclick = () => openContactsManager(pickMode);
  document.getElementById("cf-save").onclick = async () => {
    const payload = {
      name: document.getElementById("cf-name").value.trim(),
      email: document.getElementById("cf-email").value.trim(),
      phone: document.getElementById("cf-phone").value.trim(),
      notes: document.getElementById("cf-notes").value.trim(),
    };
    if (!payload.name || !payload.email) return toast("Nombre y email son obligatorios", "error");
    try {
      if (c) await api(`/contacts/${c.id}`, { method: "PUT", body: JSON.stringify(payload) });
      else await api("/contacts", { method: "POST", body: JSON.stringify(payload) });
      toast("Contacto guardado", "ok");
    } catch (e) { toast(e.message, "error"); }
    openContactsManager(pickMode);
  };
}

/* ============================================================ accounts */
function openAccountsModal() {
  const rows = state.accounts.map(a => `
    <div class="contact-item">
      <div><b>${esc(a.email)}</b><div class="c-email">${esc(a.display_name || "")} · ${a.is_default ? "predeterminada" : ""}</div></div>
      <div><button class="btn-ghost btn btn-sm" data-edit="${a.id}">Editar</button></div>
    </div>`).join("");
  openModal(`
    <h2>Cuentas de correo</h2>
    <div>${rows || `<div class="empty">Sin cuentas</div>`}</div>
    <div class="actions">
      <button class="btn-ghost btn" id="acc-close">Cerrar</button>
      <button class="btn-primary btn" id="acc-new">+ Nueva cuenta</button>
    </div>`);
  document.getElementById("acc-close").onclick = closeModal;
  document.getElementById("acc-new").onclick = () => openAccountForm();
  document.querySelectorAll("[data-edit]").forEach(b => {
    b.onclick = () => openAccountForm(parseInt(b.dataset.edit));
  });
}

function openAccountForm(accountId) {
  const acc = accountId ? state.accounts.find(a => a.id === accountId) : null;
  const v = (k, d) => acc ? (acc[k] || d) : d;
  openModal(`
    <h2>${acc ? "Editar cuenta" : "Nueva cuenta"}</h2>
    <div class="modal-grid">
      <div class="field full"><label>Correo (remitente)</label><input id="f-email" value="${esc(v("email", ""))}" placeholder="usuario@ecc-sa.com.mx"></div>
      <div class="field full"><label>Nombre a mostrar</label><input id="f-dname" value="${esc(v("display_name", ""))}" placeholder="Nombre Apellido"></div>
      <div class="field"><label>IMAP host</label><input id="f-imap" value="${esc(v("imap_host", "imap.secureserver.net"))}"></div>
      <div class="field"><label>IMAP puerto</label><input id="f-imap-port" value="${esc(v("imap_port", "993"))}"></div>
      <div class="field"><label>SMTP host</label><input id="f-smtp" value="${esc(v("smtp_host", "smtp.secureserver.net"))}"></div>
      <div class="field"><label>SMTP puerto</label><input id="f-smtp-port" value="${esc(v("smtp_port", "465"))}"></div>
      <div class="field"><label>Usuario</label><input id="f-user" value="${esc(v("username", ""))}"></div>
      <div class="field"><label>Contraseña ${acc ? "(dejar vacío = no cambiar)" : ""}</label><input id="f-pass" type="password"></div>
      <div class="field full"><label>Teléfono</label><input id="f-phone" value="${esc(v("phone", ""))}" placeholder="+52 81 0000 0000"></div>
      <div class="field full"><label>Firma HTML ${acc ? "" : "(vacía al crear = se genera automáticamente)"}</label><textarea id="f-sig">${esc(v("signature_html", ""))}</textarea></div>
    </div>
    <div class="actions">
      <button class="btn-ghost btn" id="f-cancel">Cancelar</button>
      <button class="btn-ghost btn" id="f-test">Probar conexión</button>
      ${acc ? `<button class="btn-danger btn" id="f-del">Eliminar</button>` : ""}
      <button class="btn-primary btn" id="f-save">Guardar</button>
    </div>`);
  document.getElementById("f-cancel").onclick = () => openAccountsModal();
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
      phone: document.getElementById("f-phone").value.trim(),
      signature_html: document.getElementById("f-sig").value,
      is_default: false,
    };
  }
}

/* ============================================================ notifications */
let notifTimer = null;
function startNotifications() {
  if (notifTimer) clearInterval(notifTimer);
  const tick = async () => {
    try {
      const res = await api("/notifications");
      const total = res.reduce((n, r) => n + (r.unread || 0), 0);
      const badge = document.getElementById("notif-badge");
      if (badge && !state.unreadOnly) badge.textContent = total ? total : "";
      if (total > 0) toast(`📬 ${total} correo(s) sin leer`, "ok");
    } catch (e) {}
  };
  tick();
  notifTimer = setInterval(tick, 60000);
}

/* ============================================================ init */
(async function init() {
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