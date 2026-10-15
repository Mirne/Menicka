const $ = (s) => document.querySelector(s);
const state = { restaurants: [], menus: [], votes: [] };

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
const fmtTime = (iso) => (iso ? new Date(iso).toLocaleTimeString("sk-SK", { hour: "2-digit", minute: "2-digit" }) : "");

function renderTally() {
  const by = new Map();
  for (const v of state.votes) {
    if (!by.has(v.restaurant_id)) by.set(v.restaurant_id, []);
    by.get(v.restaurant_id).push(v);
  }
  const names = new Map(state.restaurants.map((r) => [r.id, r.name]));
  const rows = [...by.entries()].sort((a, b) => b[1].length - a[1].length);
  $("#tally").innerHTML = rows.length
    ? rows.map(([rid, vs]) => `<div class="t"><strong>${esc(names.get(rid) || "?")} · ${vs.length}</strong>
        <div class="who">${vs.map((v) => esc(v.name) + (v.note ? ` <span class="muted">(${esc(v.note)})</span>` : "")).join(", ")}</div></div>`).join("")
    : `<p class="muted">Dnes ešte nikto nehlasoval.</p>`;
}

function renderSelects() {
  const sel = $("#vote-restaurant");
  const cur = sel.value || store.get("menicka.restaurant");
  sel.innerHTML = state.restaurants.map((r) => `<option value="${r.id}">${esc(r.name)}</option>`).join("");
  if (cur && state.restaurants.some((r) => String(r.id) === String(cur))) sel.value = cur;
  $("#restaurant-list").innerHTML = state.restaurants.map((r) => `<li>
      <div><strong>${esc(r.name)}</strong> <span class="badge">${esc(r.detected_kind)}</span>
      <div class="url">${esc(r.url)}${r.selector ? ` · <code>${esc(r.selector)}</code>` : ""}${r.daily_section ? ` · sekcia „${esc(r.daily_section)}“` : ""}${r.also ? ` · aj „${esc(r.also)}“` : ""}</div></div>
      <button class="ghost small" data-del="${r.id}">Odstrániť</button></li>`).join("")
    || `<li class="muted">Zatiaľ žiadne reštaurácie.</li>`;
}

function renderMenus() {
  if (!state.menus.length) {
    $("#menus").innerHTML = `<p class="muted">Žiadne reštaurácie. Pridaj ich dole v sekcii Reštaurácie.</p>`;
    return;
  }
  const count = new Map();
  for (const v of state.votes) count.set(v.restaurant_id, (count.get(v.restaurant_id) || 0) + 1);
  $("#menus").innerHTML = state.menus.map(({ restaurant: r, result: m, fetched_at }) => {
    const body = m.sections.map((s) => `<div class="sec"><h4>${esc(s.name)}</h4>${s.items.map((i) => `
        <div class="item"><div>${esc(i.name)}${i.description ? `<div class="desc">${esc(i.description)}</div>` : ""}</div>
        <span class="price">${fmtPrice(i.price)}</span></div>`).join("")}</div>`).join("");
    const found = m.error && m.found_sections.length
      ? `<p class="muted">Sekcie na stránke: ${m.found_sections.map(esc).join(", ")}.<br>
         Ktorá je denné menu, nastavíš v <code>restaurants.yaml</code> cez <code>daily_section</code>.</p>` : "";
    const images = m.from_image && m.images.length
      ? `<a class="muted small-link" href="${esc(m.images[0])}" target="_blank" rel="noopener">Prečítané z obrázka menu, môžu tam byť drobné preklepy</a>`
      : !m.sections.length && m.images.length
        ? `<div class="links"><span class="muted">Obrázky s menu:</span>${m.images.map((src, n) => `<a href="${esc(src)}" target="_blank" rel="noopener">Obrázok ${n + 1}</a>`).join("")}</div>` : "";
    const links = !m.sections.length && m.links.length
      ? `<div class="links"><span class="muted">Možno je menu tu:</span>${m.links.map((l) => `<a href="${esc(l)}" target="_blank" rel="noopener">${esc(l)}</a>`).join("")}</div>` : "";
    const debug = m.error
      ? `<a class="muted small-link" href="/api/restaurants/${r.id}/source">Stiahnuť HTML stránky na kontrolu</a>` : "";
    const n = count.get(r.id) || 0;
    return `<article class="card">
      <header><h3><a href="${esc(m.source_url || r.url)}" target="_blank" rel="noopener">${esc(r.name)}</a></h3>
        ${n ? `<span class="badge">${n} ${n === 1 ? "ide" : "idú"}</span>` : ""}</header>
      ${m.error ? `<div class="error">${esc(m.error)}</div>` : ""}
      ${found}${body}${images}${links}${debug}
      <footer><span class="muted">stiahnuté ${fmtTime(fetched_at)}</span>
        <button class="small" data-go="${r.id}">Idem sem</button></footer>
    </article>`;
  }).join("");
}

function render() { renderSelects(); renderTally(); renderMenus(); }

async function loadVotes() {
  const v = await api("/api/votes");
  state.votes = v.votes;
  renderTally();
  renderMenus();
}

async function loadAll() {
  const [restaurants, votes] = await Promise.all([api("/api/restaurants"), api("/api/votes")]);
  state.restaurants = restaurants;
  state.votes = votes.votes;
  $("#today").textContent = new Date(votes.day).toLocaleDateString("sk-SK", { weekday: "long", day: "numeric", month: "numeric" });
  render();
  state.menus = await api("/api/menus");
  renderMenus();
}

async function vote(restaurantId) {
  const name = $("#vote-name").value.trim();
  if (!name) { $("#vote-name").focus(); toast("Najprv zadaj meno"); return; }
  store.set("menicka.name", name);
  store.set("menicka.restaurant", restaurantId);
  const v = await api("/api/votes", { method: "POST", body: JSON.stringify({ name, restaurant_id: Number(restaurantId), note: $("#vote-note").value }) });
  state.votes = v.votes;
  $("#vote-restaurant").value = restaurantId;
  renderTally(); renderMenus();
  toast("Uložené");
}

$("#vote-form").addEventListener("submit", (e) => { e.preventDefault(); vote($("#vote-restaurant").value).catch((err) => toast(err.message)); });
$("#vote-clear").addEventListener("click", async () => {
  const name = $("#vote-name").value.trim();
  if (!name) return;
  const v = await api(`/api/votes/${encodeURIComponent(name)}`, { method: "DELETE" });
  state.votes = v.votes; renderTally(); renderMenus(); toast("Hlas zrušený");
});
$("#menus").addEventListener("click", (e) => {
  const b = e.target.closest("[data-go]");
  if (b) vote(b.dataset.go).catch((err) => toast(err.message));
});
$("#refresh").addEventListener("click", async (e) => {
  e.target.disabled = true;
  try { await api("/api/menus/refresh", { method: "POST" }); state.menus = await api("/api/menus"); renderMenus(); toast("Menu obnovené"); }
  catch (err) { toast(err.message); }
  finally { e.target.disabled = false; }
});
$("#add-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.submitter; btn.disabled = true;
  try {
    await api("/api/restaurants", { method: "POST", body: JSON.stringify({
      name: $("#add-name").value, url: $("#add-url").value, kind: $("#add-kind").value,
      selector: $("#add-selector").value || null, daily_section: $("#add-daily").value || null,
      also: $("#add-also").value || null }) });
    e.target.reset();
    await loadAll();
    toast("Reštaurácia pridaná");
  } catch (err) { toast(err.message); }
  finally { btn.disabled = false; }
});
$("#restaurant-list").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-del]");
  if (!b || !confirm("Odstrániť reštauráciu aj s dnešnými hlasmi?")) return;
  await api(`/api/restaurants/${b.dataset.del}`, { method: "DELETE" });
  await loadAll();
});

$("#vote-name").value = store.get("menicka.name") || "";
loadAll().catch((err) => toast(err.message));
setInterval(() => loadVotes().catch(() => {}), 30000);
