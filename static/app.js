const state = {
  token: localStorage.getItem("hubmail_token"),
  user: null,
  accounts: [],
  currentAccountId: null,
  folders: [],
  currentFolder: "INBOX",
  messages: [],
  total: 0,
  page: 1,
  q: "",
  unreadOnly: false,
  currentMsgId: null,
  composeAttachments: [],
};

const app = document.getElementById("app");
const modalRoot = document.getElementById("modal-root");
const toastRoot = document.getElementById("toast-root");

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

function openModal(html) {
  modalRoot.innerHTML = `<div class="modal-backdrop"><div class="modal">${html}</div></div>`;
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
    try {
      const data = await api("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
      state.token = data.token;
      state.user = data.user;
      localStorage.setItem("hubmail_token", data.token);
      await boot();
    } catch (e) {
      toast(e.message, "error");
    }
  };
  document.getElementById("lg-btn").onclick = doLogin;
  document.getElementById("lg-pass").addEventListener("keydown", e => { if (e.key === "Enter") doLogin(); });
}

function logout() {
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
    await loadFolders();
    state.currentFolder = "INBOX";
    await loadMessages();
    renderShell();
    startNotifications();
  } catch (e) {
    toast(e.message, "error");
  }
}

async function loadAccounts() {
  state.accounts = await api("/accounts");
}

async function loadFolders() {
  if (!state.currentAccountId) return;
  state.folders = await api(`/accounts/${state.currentAccountId}/folders`);
}

async function loadMessages() {
  if (!state.currentAccountId) return;
  const qs = `?folder=${encodeURIComponent(state.currentFolder)}&page=${state.page}&q=${encodeURIComponent(state.q)}&unread_only=${state.unreadOnly}`;
  const data = await api(`/accounts/${state.currentAccountId}/messages${qs}`);
  state.messages = data.messages;
  state.total = data.total;
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
}

function renderSidebar() {
  const sb = document.getElementById("sidebar");
  const list = state.accounts.map(acc => {
    const accFolders = state.currentAccountId === acc.id
      ? state.folders.map(f => {
          const isInbox = f.name.toUpperCase() === "INBOX";
          return `<li class="${f.name === state.currentFolder ? "active" : ""}" data-folder="${esc(f.name)}">${esc(f.name)}</li>`;
        }).join("")
      : "";
    return `
      <div class="account-block">
        <div class="account-head" data-acc="${acc.id}" title="Cuentas y firma">
          <div>${esc(acc.display_name || acc.email)}<br><small>${esc(acc.email)}</small></div>
        </div>
        <ul class="folders">${accFolders}</ul>
      </div>`;
  }).join("");

  sb.innerHTML = `
    <div class="side-actions">
      <button class="btn-ghost btn" id="sb-compose">✉️ Redactar</button>
      <button class="btn-ghost btn" id="sb-accounts">⚙️ Cuentas y firma</button>
    </div>
    ${list}`;

  document.getElementById("sb-compose").onclick = () => { sb.classList.remove("open"); openCompose(); };
  document.getElementById("sb-accounts").onclick = () => { sb.classList.remove("open"); openAccountsModal(); };

  sb.querySelectorAll(".account-head").forEach(el => {
    el.onclick = () => {
      const id = parseInt(el.dataset.acc);
      if (id !== state.currentAccountId) {
        state.currentAccountId = id;
        state.currentFolder = "INBOX";
        state.page = 1;
        state.q = "";
        state.unreadOnly = false;
        loadFolders()
          .then(() => loadMessages())
          .then(renderContent)
          .catch(e => toast(e.message, "error"));
      }
    };
  });
  sb.querySelectorAll(".folders li").forEach(el => {
    el.onclick = () => {
      state.currentFolder = el.dataset.folder;
      state.page = 1;
      state.q = "";
      state.unreadOnly = false;
      loadMessages().then(renderContent).catch(e => toast(e.message, "error"));
    };
  });
}

function renderContent() {
  const content = document.getElementById("content");
  const totalUnread = state.messages.reduce((n, m) => n + (m.unread ? 1 : 0), 0);
  document.getElementById("notif-badge").textContent = state.unreadOnly ? "✓" : (totalUnread ? totalUnread : "");

  const pages = Math.max(1, Math.ceil(state.total / 25));
  const msgs = state.messages.length
    ? state.messages.map(m => {
        const from = m.from[0];
        const sender = from ? (from.name || from.email) : "?";
        return `
        <div class="msg-item ${m.unread ? "unread" : ""}" data-id="${esc(m.id)}">
          <div class="row1">
            <div class="from">${esc(sender)}</div>
            <div class="date">${esc(m.date)}</div>
          </div>
          <div class="subject">${m.flagged ? "★ " : ""}${esc(m.subject)}</div>
        </div>`;
      }).join("")
    : `<div class="empty">Sin mensajes</div>`;

  content.innerHTML = `
    <div id="list-pane">
      <div class="list-toolbar">
        <div class="folder-title">${esc(state.currentFolder)} ${state.unreadOnly ? "(no leídos)" : ""}</div>
        <input id="search-box" placeholder="Buscar..." value="${esc(state.q)}">
        <button class="btn-ghost btn btn-sm" id="btn-refresh">⟳</button>
        <button class="btn-ghost btn btn-sm" id="btn-unread">${state.unreadOnly ? "Todo" : "No leídos"}</button>
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

  document.querySelectorAll("#message-list .msg-item").forEach(el => {
    el.onclick = () => openMessage(el.dataset.id);
  });

  const dp = document.getElementById("detail-pane");
  if (state.currentMsgId) {
    loadMessageDetail(state.currentMsgId).then(m => {
      if (document.getElementById("detail-pane")) renderDetail(m);
    }).catch(() => {});
  } else {
    dp.innerHTML = `<div class="empty" style="margin-top:80px">Selecciona un mensaje para leerlo</div>`;
  }
}

async function openMessage(id) {
  state.currentMsgId = id;
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
  }
}

async function loadMessageDetail(id) {
  return api(`/accounts/${state.currentAccountId}/messages/${encodeURIComponent(id)}?folder=${encodeURIComponent(state.currentFolder)}`);
}

function renderDetail(m) {
  const dp = document.getElementById("detail-pane");
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

  dp.innerHTML = `
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

  dp.classList.add("open");
  document.getElementById("d-back").onclick = () => { state.currentMsgId = null; dp.classList.remove("open"); };
  document.getElementById("d-del").onclick = async () => {
    if (!confirm("¿Eliminar este mensaje?")) return;
    await api(`/accounts/${state.currentAccountId}/messages/${encodeURIComponent(m.id)}?folder=${encodeURIComponent(state.currentFolder)}&action=delete`, { method: "PATCH" }).catch(e => toast(e.message, "error"));
    state.currentMsgId = null;
    await loadMessages();
    renderContent();
    toast("Mensaje eliminado", "ok");
  };
  document.getElementById("d-flag").onclick = async () => {
    await api(`/accounts/${state.currentAccountId}/messages/${encodeURIComponent(m.id)}?folder=${encodeURIComponent(state.currentFolder)}&action=${m.flagged ? "unflag" : "flag"}`, { method: "PATCH" });
    m.flagged = !m.flagged;
    renderDetail(m);
  };
  document.getElementById("d-reply").onclick = () => {
    const f = m.from[0];
    openCompose({ to: [f && f.email], subject: m.subject.startsWith("Re:") ? m.subject : "Re: " + m.subject, reply_to: m.message_id });
  };
  document.getElementById("d-fwd").onclick = () => {
    openCompose({ subject: m.subject.startsWith("Fwd:") ? m.subject : "Fwd: " + m.subject });
  };
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
    </div>`);

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
  document.getElementById("c-contacts").onclick = () => {
    api("/contacts").then(contacts => {
      openModal(`
        <h2>Contactos compartidos</h2>
        <div>${contacts.map(c =>
          `<div class="contact-item"><div><b>${esc(c.name)}</b><div class="c-email">${esc(c.email)}</div></div>
           <button class="btn-ghost btn btn-sm" data-email="${esc(c.email)}">Usar</button></div>`).join("") || `<div class="empty">Sin contactos</div>`}</div>
        <div class="actions"><button class="btn-ghost btn" id="cc-close">Cerrar</button></div>`);
      document.getElementById("cc-close").onclick = () => openCompose(prefill);
      document.querySelectorAll("[data-email]").forEach(b => {
        b.onclick = () => {
          const to = document.getElementById("c-to");
          to.value = to.value ? to.value + ", " + b.dataset.email : b.dataset.email;
          openCompose(prefill);
        };
      });
    });
  };
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
  }
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
      <div class="field full"><label>Firma HTML</label><textarea id="f-sig">${esc(v("signature_html", ""))}</textarea></div>
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
    return;
  }
  try {
    state.user = await api("/auth/me");
    await boot();
  } catch (e) {
    renderLogin();
  }
})();