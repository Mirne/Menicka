"""Exercise vote rendering and draft state with the real browser script in Node."""
import json
import pathlib
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_other_place_labels_visibility_and_drafts():
    static = pathlib.Path(__file__).parent.parent / "app" / "static"
    script = r'''
const fs = require("fs"), vm = require("vm"), assert = require("node:assert/strict");
const elements = new Map();
function el(selector) {
  if (!elements.has(selector)) elements.set(selector, {
    value: "", hidden: false, innerHTML: "", dataset: {},
    classList: { add() {}, remove() {} }, addEventListener() {}, focus() {},
  });
  return elements.get(selector);
}
const context = vm.createContext({
  document: { documentElement: {}, querySelector: el, querySelectorAll: () => [] },
  location: { search: "?lang=en" }, navigator: { languages: ["en"] }, URLSearchParams,
  localStorage: { getItem: () => null, setItem() {} },
  setTimeout: () => 0, clearTimeout() {}, setInterval() {}, console,
});
vm.runInContext(fs.readFileSync(STATIC + "/i18n.js", "utf8"), context);
vm.runInContext(fs.readFileSync(STATIC + "/app.js", "utf8")
  .replace("loadAll().catch((err) => toast(err.message));", ""), context);
vm.runInContext(`
  state.restaurants = [{ id: 1, name: "Bistro" }, { id: 2, other: true }, { id: 3, skip: true }];
  state.day = "2026-10-26";
  state.votes = [
    { name: "Robo", restaurant_id: 2, note: "Sushi bar" },
    { name: "Eva", restaurant_id: 2, note: "sushi bar" },
    { name: "Jana", restaurant_id: 2, note: "Doma" },
    { name: "Peter", restaurant_id: 2, note: "" },
    { name: "Skip", restaurant_id: 3, note: "" },
  ];
  renderTally(); renderChoices();
`, context);
assert.ok(el("#tally").innerHTML.includes("<strong>Sushi bar · 2</strong>"));
assert.ok(el("#tally").innerHTML.includes("Robo, Eva"));
assert.ok(el("#tally").innerHTML.includes("<strong>Doma · 1</strong>"));
assert.ok(el("#tally").innerHTML.includes("<strong>Somewhere else · 1</strong>"));
assert.equal(el("#other-details").hidden, true);
el("#vote-name").value = "Robo";
vm.runInContext("renderChoices()", context);
assert.equal(el("#other-details").hidden, false);
assert.equal(el("#other-note").value, "Sushi bar");
el("#other-note").value = "Unfinished text";
vm.runInContext("state.noteDirty = true; renderChoices()", context);
assert.equal(el("#other-note").value, "Unfinished text");
el("#vote-name").value = "Someone else";
vm.runInContext("renderChoices()", context);
assert.equal(el("#other-details").hidden, true);
assert.equal(el("#other-note").value, "");
el("#vote-name").value = "Robo";
vm.runInContext("state.votes = state.votes.filter(v => v.name !== 'Robo'); renderChoices()", context);
assert.equal(el("#other-details").hidden, true);
vm.runInContext(`state.votes = [{ name: "<img>", restaurant_id: 2, note: "<script>" }]; renderTally()`, context);
assert.ok(el("#tally").innerHTML.includes("&lt;script&gt;"));
assert.ok(el("#tally").innerHTML.includes("&lt;img&gt;"));
for (const lang of ["sk", "cs", "en"]) {
  for (const key of ["otherName", "otherDetails", "otherPh", "saveOther"]) {
    assert.notEqual(vm.runInContext(`I18N.make('${lang}').t('${key}')`, context), key);
  }
}
'''
    subprocess.run(["node", "-e", f"const STATIC = {json.dumps(str(static))};\n" + script],
                   check=True, capture_output=True, text=True, timeout=30)
