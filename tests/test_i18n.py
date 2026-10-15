"""The controls are translated into Slovak, Czech and English; the language comes from the browser."""
import json
import pathlib
import shutil
import subprocess

import pytest


I18N_JS = pathlib.Path(__file__).parent.parent / "app" / "static" / "i18n.js"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def run_js(code: str):
    script = f"const I18N = require({json.dumps(str(I18N_JS))});\n{code}"
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout)


@needs_node
def test_languages_have_the_same_texts_and_detection():
    result = run_js("""
        const keys = {};
        for (const l of I18N.languages) {
          const L = I18N.make(l);
          keys[l] = ["question", "save", "noVotes", "fetched", "going", "skipName"].map((k) => typeof L.t(k) === "function" ? L.t(k)(2) : L.t(k, {time: "12:00"}));
        }
        console.log(JSON.stringify({
          keys, keySets: I18N.languages.map((l) => I18N.keys(l).sort().join(",")),
          detect: [["cs-CZ", "en"], ["sk"], ["de-DE", "cs"], ["de-DE"], [], ["EN-us"]].map((x) => I18N.detect(x)),
        }));""")
    assert result["detect"] == ["cs", "sk", "cs", "en", "en", "en"]
    assert result["keys"]["cs"] == ["Kam jdeš na oběd?", "Uložit", "Dnes ještě nikdo nehlasoval.", "staženo 12:00", "jdou", "Nejdu na oběd"]
    assert result["keys"]["en"][0] == "Where are you going for lunch?"
    assert len(set(result["keySets"])) == 1  # sk, cs and en define the same texts
