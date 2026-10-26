"""Map behavior, including voting-only destinations and an unavailable map CDN."""
import json
import pathlib
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_map_markers_navigation_and_fallback():
    path = pathlib.Path(__file__).parent.parent / "app" / "static" / "map.js"
    script = r'''
const vm = require("vm"), fs = require("fs"), assert = require("node:assert/strict");
function element() {
  return { children: [], hidden: false, textContent: "", handlers: {}, classes: new Set(),
    append(...children) { this.children.push(...children); },
    replaceChildren() { this.children = []; },
    addEventListener(type, cb) { this.handlers[type] = cb; },
    classList: { add() {}, remove() {} },
  };
}
function setup(fail = false) {
  const elements = new Map();
  const document = { head: { append(el) { if (el.src) el.onerror(); } },
    createElement: () => element(),
    querySelector: (selector) => {
      if (!elements.has(selector)) elements.set(selector, element());
      return elements.get(selector);
    },
  };
  const record = { markers: [], bounds: null, maps: 0 };
  const map = { invalidateSize() {}, getZoom: () => 13,
    getBoundsZoom(bounds) { record.bounds = bounds; return 13; }, setView(coords) { record.view = coords; },
  };
  const layer = { addTo() { return this; }, clearLayers() { record.markers = []; } };
  const L = { map() { record.maps++; return map; }, tileLayer: () => ({ addTo() {} }),
    layerGroup: () => layer, divIcon: (opts) => opts,
    marker(coords, opts) {
      const marker = { coords, opts, bindTooltip(label, options) { this.label = label; this.tooltipOptions = options; return this; },
        bindPopup(popup) { this.popup = popup; return this; },
        addTo() { record.markers.push(this); return this; }, openPopup() { this.open = true; },
      };
      return marker;
    },
  };
  const ctx = vm.createContext({ document, L: fail ? undefined : L, setTimeout: () => 1, clearTimeout() {} });
  vm.runInContext(fs.readFileSync(MAP_JS, "utf8"), ctx);
  return { ctx, record, elements };
}
const restaurants = [
  { id: 1, name: "<Cafe>", address: "Street 1", latitude: 49.2, longitude: 16.6 },
  { id: 2, name: "Voting only", has_menu: false, latitude: 49.21, longitude: 16.59 },
  { id: 3, skip: true, latitude: 49.2, longitude: 16.6 },
  { id: 4, other: true, latitude: 49.2, longitude: 16.6 },
  { id: 5, name: "Invalid", latitude: 100, longitude: 16.6 },
  { id: 6, name: "Unlocated", latitude: null, longitude: null },
];
(async () => {
  const { ctx, record, elements } = setup();
  await ctx.RestaurantMap.render(restaurants, (key) => key);
  assert.equal(record.markers.length, 3);
  const officeMarker = record.markers[0];
  assert.equal(officeMarker.popup.children[0].textContent, "mapOffice");
  assert.equal(officeMarker.popup.children[1].textContent, "Šumavská 31, Brno");
  assert.equal(officeMarker.opts.icon.html, "★");
  assert.ok(officeMarker.opts.icon.className.includes("office-pin"));
  assert.equal(officeMarker.tooltipOptions.permanent, false);
  assert.deepEqual(Array.from(record.view), [49.2098916, 16.5925845]);
  assert.ok(Math.abs((record.bounds[0][0] + record.bounds[1][0]) / 2 - record.view[0]) < 1e-8);
  assert.ok(Math.abs((record.bounds[0][1] + record.bounds[1][1]) / 2 - record.view[1]) < 1e-8);
  assert.equal(record.bounds.length, 2);
  assert.equal(record.markers[1].popup.children[0].textContent, "<Cafe>");
  assert.ok(record.markers[1].popup.children[2].href.includes("destination=49.2,16.6"));
  const link = elements.get("#map-places").children[2].children[0];
  let prevented = false;
  link.handlers.click({ preventDefault() { prevented = true; } });
  assert.ok(prevented && record.markers[2].open);
  assert.equal(elements.get("#map-status").hidden, true);
  await ctx.RestaurantMap.render(restaurants.slice(0, 1), (key) => key);
  assert.equal(record.maps, 1);
  assert.equal(record.markers.length, 2);
  const fallback = setup(true);
  await fallback.ctx.RestaurantMap.render(restaurants, (key) => key);
  assert.equal(fallback.elements.get("#restaurant-map").hidden, true);
  assert.equal(fallback.elements.get("#map-status").textContent, "mapUnavailable");
  assert.equal(fallback.elements.get("#map-places").children.length, 3);
  const fallbackLink = fallback.elements.get("#map-places").children[0].children[0];
  assert.ok(fallbackLink.href.includes("destination="));
  fallbackLink.handlers.click({ preventDefault() { throw Error("Navigation should stay available"); } });
})().catch((e) => { console.error(e); process.exitCode = 1; });
'''
    subprocess.run(["node", "-e", f"const MAP_JS = {json.dumps(str(path))};\n" + script],
                   capture_output=True, text=True, check=True, timeout=30)
