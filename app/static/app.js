const $ = (s) => document.querySelector(s);
const state = { restaurants: [], menus: [], votes: [], noteOwner: "", noteDirty: false };

// Language from the browser; "?lang=cs" overrides it (handy for checking).
const forced = new URLSearchParams(location.search).get("lang");
const L = I18N.make(I18N.detect(forced ? [forced] : navigator.languages || [navigator.language]));
const t = L.t;
document.documentElement.lang = L.lang;
for (const el of document.querySelectorAll("[data-i18n]")) el.textContent = t(el.dataset.i18n);
for (const el of document.querySelectorAll("[data-i18n-title]")) el.title = t(el.dataset.i18nTitle);
for (const el of document.querySelectorAll("[data-i18n-placeholder]")) el.placeholder = t(el.dataset.i18nPlaceholder);
const rname = (r) => (!r ? "?" : r.skip ? t("skipName") : r.other ? t("otherName") : r.name);

const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch {} },
};

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("on");
  clearTimeout(toast.h);
  toast.h = setTimeout(() => t.classList.remove("on"), 2500);
}

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : (j.detail || []).map((d) => d.msg).join(", ");
    } catch {}
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

const fmtPrice = (p) => (p == null ? "" : `${Number.isInteger(p) ? p : p.toFixed(2).replace(".", ",")} Kč`);
const fmtTime = (iso) => (iso ? new Date(iso).toLocaleTimeString(L.locale, { hour: "2-digit", minute: "2-digit" }) : "");

function renderTally() {
  const by = new Map();
  for (const v of state.votes) {
    if (!by.has(v.restaurant_id)) by.set(v.restaurant_id, []);
    by.get(v.restaurant_id).push(v);
  }
  const byId = new Map(state.restaurants.map((r) => [r.id, r]));
  const skip = new Set(state.restaurants.filter((r) => r.skip).map((r) => r.id));
  // most votes first, "Nejdem na obed" always last
  const rows = [...by.entries()].sort((a, b) => skip.has(a[0]) - skip.has(b[0]) || b[1].length - a[1].length);
  $("#tally").innerHTML = rows.length
    ? rows.map(([rid, vs]) => `<div class="t${skip.has(rid) ? " skip" : ""}"><strong>${esc(rname(byId.get(rid)))} · ${vs.length}</strong>
        <div class="who">${vs.map((v) => esc(v.name) + (byId.get(rid)?.other && v.note ? ` (${esc(v.note)})` : "")).join(", ")}</div></div>`).join("")
    : `<p class="muted">${esc(t("noVotes"))}</p>`;
}

// The restaurants the person in the name field picked today.
function myChoices() {
  const me = $("#vote-name").value.trim().toLowerCase();
  return new Set(state.votes.filter((v) => me && v.name.toLowerCase() === me).map((v) => v.restaurant_id));
}

function myOtherVote() {
  const me = $("#vote-name").value.trim().toLowerCase();
  const other = state.restaurants.find((r) => r.other);
  return state.votes.find((v) => me && v.name.toLowerCase() === me && v.restaurant_id === other?.id);
}

function renderOtherNote() {
  const owner = `${state.day}:${$("#vote-name").value.trim().toLowerCase()}`;
  const vote = myOtherVote();
  $("#other-details").hidden = !vote;
  if (state.noteOwner !== owner || !vote || !state.noteDirty) {
    $("#other-note").value = vote?.note || "";
    state.noteOwner = owner;
    state.noteDirty = false;
  }
}

function renderChoices() {
  const mine = myChoices();
  $("#vote-choices").innerHTML = state.restaurants.map((r) => `<button type="button" class="choice${r.skip || r.other ? " skip" : ""}"
      data-rid="${r.id}" aria-pressed="${mine.has(r.id)}">${esc(rname(r))}</button>`).join("");
  renderOtherNote();
}

function renderMenus() {
  if (!state.menus.length) {
    $("#menus").innerHTML = `<p class="muted">${esc(t("noRestaurants"))}</p>`;
    return;
  }
  const count = new Map();
  for (const v of state.votes) count.set(v.restaurant_id, (count.get(v.restaurant_id) || 0) + 1);
  $("#menus").innerHTML = state.menus.map(({ restaurant: r, result: m, fetched_at }) => {
    const body = m.sections.map((s) => `<div class="sec">${s.name ? `<h4>${esc(s.name)}</h4>` : ""}${s.items.map((i) => `
        <div class="item"><div>${esc(i.name)}${i.description ? `<div class="desc">${esc(i.description)}</div>` : ""}</div>
        <span class="price">${fmtPrice(i.price)}</span></div>`).join("")}</div>`).join("");
    const found = m.error && m.found_sections.length
      ? `<p class="muted">${esc(t("foundSections", { list: m.found_sections.join(", ") }))}<br>${t("foundHint")}</p>` : "";
    const images = !m.sections.length && m.images.length
        ? `<div class="links"><span class="muted">${esc(t("menuImages"))}</span>${m.images.map((src, n) => `<a href="${esc(src)}" target="_blank" rel="noopener">${esc(t("image", { n: n + 1 }))}</a>`).join("")}</div>` : "";
    const links = !m.sections.length && m.links.length
      ? `<div class="links"><span class="muted">${esc(t("maybeHere"))}</span>${m.links.map((l) => `<a href="${esc(l)}" target="_blank" rel="noopener">${esc(l)}</a>`).join("")}</div>` : "";
    const debug = m.error
      ? `<a class="muted small-link" href="/api/restaurants/${r.id}/source">${esc(t("downloadHtml"))}</a>` : "";
    const n = count.get(r.id) || 0;
    return `<article class="card">
      <header><h3><a href="${esc(m.source_url || r.url)}" target="_blank" rel="noopener">${esc(r.name)}</a></h3>
        ${n ? `<span class="badge">${n} ${t("going")(n)}</span>` : ""}</header>
      ${m.error ? `<div class="error">${esc(m.error)}</div>` : ""}
      ${found}${body}${images}${links}${debug}
      <footer><span class="muted">${esc(t("fetched", { time: fmtTime(fetched_at) }))}</span></footer>
    </article>`;
  }).join("");
}

function render() { renderChoices(); renderTally(); renderMenus(); }

async function loadVotes() {
  const v = await api("/api/votes");
  if (v.day !== state.day) return loadAll();  // the day changed while the page was open
  state.votes = v.votes;
  renderChoices();
  renderTally();
  renderMenus();
}

async function loadAll() {
  const [restaurants, votes] = await Promise.all([api("/api/restaurants"), api("/api/votes")]);
  state.restaurants = restaurants;
  state.votes = votes.votes;
  state.day = votes.day;
  $("#today").textContent = new Date(votes.day).toLocaleDateString(L.locale, { weekday: "long", day: "numeric", month: "numeric" });
  render();
  state.menus = await api("/api/menus");
  renderMenus();
}

// Click a restaurant to add it to your choices or take it back. "Nejdem na obed" excludes the rest.
async function toggle(rid) {
  const name = $("#vote-name").value.trim();
  if (!name) { $("#vote-name").focus(); toast(t("enterName")); return; }
  const skipIds = new Set(state.restaurants.filter((r) => r.skip).map((r) => r.id));
  const mine = myChoices();
  if (mine.has(rid)) mine.delete(rid);
  else {
    for (const id of [...mine]) if (skipIds.has(id) || skipIds.has(rid)) mine.delete(id);
    mine.add(rid);
  }
  const v = await api("/api/votes", { method: "POST", body: JSON.stringify({ name, restaurant_ids: [...mine], other_note: $("#other-note").value.trim() }) });
  state.votes = v.votes;
  state.noteDirty = false;
  renderChoices(); renderTally(); renderMenus();
  if (state.restaurants.find((r) => r.id === rid)?.other && mine.has(rid)) $("#other-note").focus();
  toast(t(mine.size ? "saved" : "voteRemoved"));
}

async function saveOtherNote() {
  if (!myOtherVote()) return;
  const button = $("#other-save");
  button.disabled = true;
  const name = $("#vote-name").value.trim();
  const note = $("#other-note").value.trim();
  try {
    const v = await api("/api/votes", { method: "POST", body: JSON.stringify({
      name, restaurant_ids: [...myChoices()], other_note: note,
    }) });
    state.votes = v.votes;
    if ($("#vote-name").value.trim() === name && $("#other-note").value.trim() === note) state.noteDirty = false;
    renderChoices(); renderTally(); renderMenus();
    toast(t("saved"));
  } catch (err) { toast(err.message); }
  finally { button.disabled = false; }
}

$("#other-note").addEventListener("input", () => { state.noteDirty = true; });
$("#other-note").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); saveOtherNote(); }
});
$("#other-save").addEventListener("click", saveOtherNote);

$("#vote-form").addEventListener("submit", (e) => e.preventDefault());
$("#vote-choices").addEventListener("click", (e) => {
  const b = e.target.closest("[data-rid]");
  if (b) toggle(Number(b.dataset.rid)).catch((err) => toast(err.message));
});
// The name is remembered in this browser as soon as it is typed.
$("#vote-name").addEventListener("input", () => { store.set("menicka.name", $("#vote-name").value.trim()); renderChoices(); });
$("#vote-clear").addEventListener("click", async () => {
  const name = $("#vote-name").value.trim();
  if (!name) return;
  const v = await api(`/api/votes/${encodeURIComponent(name)}`, { method: "DELETE" });
  state.votes = v.votes; renderChoices(); renderTally(); renderMenus(); toast(t("voteRemoved"));
});
$("#refresh").addEventListener("click", async (e) => {
  e.target.disabled = true;
  try { await api("/api/menus/refresh", { method: "POST" }); state.menus = await api("/api/menus"); renderMenus(); toast(t("refreshed")); }
  catch (err) { toast(err.message); }
  finally { e.target.disabled = false; }
});
$("#vote-name").value = store.get("menicka.name") || "";
loadAll().catch((err) => toast(err.message));
setInterval(() => loadVotes().catch(() => {}), 30000);
