// Load the map independently: a blocked map/CDN must not stop menus or voting.
(function (root) {
  let library, map, layer, renderId = 0;
  const markers = new Map();
  const leafletVersion = "https://unpkg.com/leaflet@1.9.4/dist/";

  function loadLeaflet() {
    if (root.L?.map) return Promise.resolve(root.L);
    if (library) return library;
    library = new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("Map load timeout")), 15000);
      const css = document.createElement("link");
      css.rel = "stylesheet";
      css.href = leafletVersion + "leaflet.css";
      css.integrity = "sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=";
      css.crossOrigin = "anonymous";
      document.head.append(css);
      const script = document.createElement("script");
      script.src = leafletVersion + "leaflet.js";
      script.integrity = "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=";
      script.crossOrigin = "anonymous";
      script.onload = () => { clearTimeout(timeout); resolve(root.L); };
      script.onerror = () => { clearTimeout(timeout); reject(new Error("Map load failed")); };
      document.head.append(script);
    });
    return library;
  }

  function located(r) {
    return !r.skip && !r.other && Number.isFinite(r.latitude) && Number.isFinite(r.longitude)
      && Math.abs(r.latitude) <= 90 && Math.abs(r.longitude) <= 180;
  }

  function directions(r) {
    return `https://www.google.com/maps/dir/?api=1&destination=${r.latitude},${r.longitude}`;
  }

  function popup(r, t) {
    const box = document.createElement("div");
    box.className = "map-popup";
    for (const [tag, value] of [["strong", r.name], ["span", r.address || ""]]) {
      const el = document.createElement(tag);
      el.textContent = value;
      box.append(el);
    }
    const link = document.createElement("a");
    link.href = directions(r);
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = t("mapDirections");
    box.append(link);
    return box;
  }

  async function render(restaurants, t) {
    const current = ++renderId;
    const places = restaurants.filter(located);
    const container = document.querySelector("#restaurant-map");
    const list = document.querySelector("#map-places");
    const status = document.querySelector("#map-status");
    const layout = document.querySelector(".map-layout");
    list.replaceChildren();
    places.forEach((r, index) => {
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = directions(r);
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = `${index + 1}. ${r.name}`;
      const address = document.createElement("small");
      address.textContent = r.address || "";
      link.append(address);
      link.addEventListener("click", (event) => {
        const marker = markers.get(r.id);
        if (!marker || container.hidden) return; // keep navigation links usable without a map
        event.preventDefault();
        map.setView([r.latitude, r.longitude], Math.max(map.getZoom(), 16));
        marker.openPopup();
      });
      item.append(link);
      list.append(item);
    });
    status.hidden = false;
    status.textContent = t(places.length ? "mapLoading" : "mapEmpty");
    if (!places.length) { container.hidden = true; return; }
    try {
      const Leaflet = await loadLeaflet();
      if (current !== renderId) return;
      container.hidden = false;
      layout.classList.remove("map-unavailable");
      if (!map) {
        map = Leaflet.map(container, { scrollWheelZoom: false });
        Leaflet.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
          maxZoom: 19,
          attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        }).addTo(map);
        layer = Leaflet.layerGroup().addTo(map);
      }
      layer.clearLayers();
      markers.clear();
      places.forEach((r, index) => {
        const icon = Leaflet.divIcon({ className: "restaurant-pin", html: String(index + 1),
          iconSize: [28, 28], iconAnchor: [14, 14] });
        const label = document.createElement("span");
        label.textContent = r.name;
        const marker = Leaflet.marker([r.latitude, r.longitude], { icon, title: r.name, alt: r.name })
          .bindTooltip(label).bindPopup(popup(r, t)).addTo(layer);
        markers.set(r.id, marker);
      });
      map.invalidateSize();
      map.fitBounds(places.map((r) => [r.latitude, r.longitude]), { padding: [24, 24], maxZoom: 15 });
      status.hidden = true;
    } catch {
      if (current !== renderId) return;
      container.hidden = true;
      layout.classList.add("map-unavailable");
      status.textContent = t("mapUnavailable");
    }
  }

  root.RestaurantMap = { render };
})(globalThis);
