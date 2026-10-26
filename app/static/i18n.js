// Automatic language of the controls: Slovak, Czech or English, picked from the browser's
// languages. The menus themselves (dishes, sections, notes on the cards) are not translated.
(function (root) {
  const LOCALES = { sk: "sk-SK", cs: "cs-CZ", en: "en-GB" };

  const UI = {
    sk: {
      refresh: "↻ Obnoviť menu", refreshTitle: "Znova stiahnuť menu zo všetkých reštaurácií",
      question: "Kam ideš na obed?", name: "Meno", namePh: "Tvoje meno", choose: "Vyber jednu alebo viac reštik",
      clear: "Zrušiť môj hlas", loading: "Načítavam menu…",
      noVotes: "Dnes ešte nikto nehlasoval.", noRestaurants: "Žiadne reštaurácie. Pridaj ich do súboru restaurants.yaml.",
      foundSections: "Sekcie na stránke: {list}.",
      foundHint: "Ktorá je denné menu, nastavíš v <code>restaurants.yaml</code> cez <code>daily_section</code>.",
      menuImages: "Obrázky s menu:", image: "Obrázok {n}", maybeHere: "Možno je menu tu:",
      downloadHtml: "Stiahnuť HTML stránky na kontrolu", fetched: "stiahnuté {time}",
      enterName: "Najprv zadaj meno", saved: "Uložené", voteRemoved: "Hlas zrušený", refreshed: "Menu obnovené",
      going: (n) => (n === 1 ? "ide" : "idú"),
      skipName: "Nejdem na obed",
      mapTitle: "Mapa podnikov", mapLoading: "Načítavam mapu…", mapUnavailable: "Mapu sa nepodarilo načítať. Použi odkazy na podniky.",
      mapDirections: "Navigovať", mapEmpty: "Polohy podnikov zatiaľ nie sú nastavené.",
      otherName: "Inde",
      otherDetails: "Kam konkrétne?", otherPh: "Názov reštaurácie alebo miesto",
    },
    cs: {
      refresh: "↻ Obnovit menu", refreshTitle: "Znovu stáhnout menu ze všech restaurací",
      question: "Kam jdeš na oběd?", name: "Jméno", namePh: "Tvoje jméno", choose: "Vyber jednu nebo více restaurací",
      clear: "Zrušit můj hlas", loading: "Načítám menu…",
      noVotes: "Dnes ještě nikdo nehlasoval.", noRestaurants: "Žádné restaurace. Přidej je do souboru restaurants.yaml.",
      foundSections: "Sekce na stránce: {list}.",
      foundHint: "Která je denní menu, nastavíš v <code>restaurants.yaml</code> přes <code>daily_section</code>.",
      menuImages: "Obrázky s menu:", image: "Obrázek {n}", maybeHere: "Možná je menu tady:",
      downloadHtml: "Stáhnout HTML stránky ke kontrole", fetched: "staženo {time}",
      enterName: "Nejdřív zadej jméno", saved: "Uloženo", voteRemoved: "Hlas zrušen", refreshed: "Menu obnoveno",
      going: (n) => (n === 1 ? "jde" : "jdou"),
      skipName: "Nejdu na oběd",
      mapTitle: "Mapa podniků", mapLoading: "Načítám mapu…", mapUnavailable: "Mapu se nepodařilo načíst. Použij odkazy na podniky.",
      mapDirections: "Navigovat", mapEmpty: "Polohy podniků zatím nejsou nastavené.",
      otherName: "Jinde",
      otherDetails: "Kam konkrétně?", otherPh: "Název restaurace nebo místo",
    },
    en: {
      refresh: "↻ Refresh menus", refreshTitle: "Download the menus from all restaurants again",
      question: "Where are you going for lunch?", name: "Name", namePh: "Your name", choose: "Pick one or more restaurants",
      clear: "Remove my vote", loading: "Loading menus…",
      noVotes: "Nobody has voted today yet.", noRestaurants: "No restaurants. Add them to restaurants.yaml.",
      foundSections: "Sections on the page: {list}.",
      foundHint: "Set which one is the daily menu with <code>daily_section</code> in <code>restaurants.yaml</code>.",
      menuImages: "Menu pictures:", image: "Picture {n}", maybeHere: "The menu may be here:",
      downloadHtml: "Download the page HTML for checking", fetched: "fetched {time}",
      enterName: "Enter your name first", saved: "Saved", voteRemoved: "Vote removed", refreshed: "Menus refreshed",
      going: () => "going",
      skipName: "Not going to lunch",
      mapTitle: "Restaurant map", mapLoading: "Loading map…", mapUnavailable: "The map could not load. Use the restaurant links.",
      mapDirections: "Directions", mapEmpty: "Restaurant locations have not been configured yet.",
      otherName: "Somewhere else",
      otherDetails: "Where exactly?", otherPh: "Restaurant name or place",
    },
  };

  function detect(languages) {
    for (const l of languages || []) {
      const code = String(l).toLowerCase().slice(0, 2);
      if (UI[code]) return code;
    }
    return "en";
  }

  function make(lang) {
    const ui = UI[lang] || UI.en;
    return {
      lang,
      locale: LOCALES[lang] || LOCALES.en,
      t(key, vars = {}) {
        const v = ui[key] ?? UI.sk[key] ?? key;
        return typeof v === "function" ? v : String(v).replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? "");
      },
    };
  }

  const api = { detect, make, languages: Object.keys(UI), keys: (lang) => Object.keys(UI[lang] || {}) };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.I18N = api;
})(typeof window !== "undefined" ? window : globalThis);
