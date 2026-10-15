# Menučka

Stránka, ktorá zbiera denné menu z reštaurácií, ktoré zadáte, a ukazuje, kto kam ide na obed.

- **Menu**: pre každú reštauráciu sa stiahne dnešné menu (pri štarte, potom každých 30 minút, alebo tlačidlom *Obnoviť menu*).
- **Ľudia**: zadáš meno a vyberieš reštiku, alebo „Nejdem na obed“. Táto možnosť je vždy posledná a netreba ju pridávať do `restaurants.yaml`. Jeden hlas na osobu a deň, ďalší ho prepíše. Hlasy platia len v daný deň: ráno je zoznam prázdny a staré hlasy sa zmažú. Otvorená stránka sa pri zmene dňa sama obnoví.
- **Jazyk**: ovládanie stránky je po slovensky, česky alebo anglicky podľa jazyka prehliadača. Iný jazyk dostane angličtinu. Menu sa neprekladá. Jazyk sa dá vynútiť adresou, napríklad `?lang=cs`.
- **Reštaurácie**: iba v súbore `restaurants.yaml`. Reštika bez `url`, napríklad Pho Eden, je len na výber v hlasovaní a nemá kartu s menu. Reštaurácia, ktorú zo súboru zmažeš, po reštarte zmizne aj zo stránky.

## Spustenie

```bash
./start.sh
```

Skript zostaví image, nájde voľný port od 47823 vyššie a vypíše adresu, napríklad <http://localhost:47823>.
Zvolený port uloží do `.env`, takže `docker compose up`, `restart` aj `down` potom používajú ten istý.
Konkrétny port: `PORT=51234 ./start.sh`.

Bez skriptu, napríklad na Windows bez bashu: `docker compose up --build`, s portom `PORT=51234 docker compose up --build`.

Logy: `docker compose logs -f`. Zastavenie: `docker compose down`.
Hlasy sú v Docker volume `menicka-data`.

## Pridanie reštaurácie

```yaml
restaurants:
  - name: Padagali
    url: https://padagali.choiceqr.com/section:menu
  - name: Everest
    url: https://www.everestbrno.cz/
  - name: Iná reštika
    url: https://example.cz/obedy
    selector: "#denni-menu"   # voliteľné: CSS selektor časti stránky s menu
```

Po úprave stačí `docker compose restart`. Popis polí `selector` a `daily_section` je nižšie.

### Ako sa menu číta

Zobrazuje sa iba dnešné denné menu. Zvyšok jedálneho lístka sa nezobrazuje.

| Typ | Kedy | Ako |
|---|---|---|
| `choiceqr` | adresa na `choiceqr.com` | Z dát stránky (`__NEXT_DATA__`) vytiahne sekcie a ponechá tú, ktorej názov znie ako denné menu: Denní, Polední, Obědové, Lunch, Daily, alebo dnešný deň v týždni. Ak taká nie je, hľadá v dátach iné menu podniku s takým názvom a skúsi ho otvoriť. |
| `html` | všetko ostatné | Ak stránka vypisuje menu po dňoch, vezme dnešný deň. Rozozná „Čtvrtek“, „Čt 15.10.“ aj samotný dátum. Pri dátume musí sedieť dnešok, takže starý týždeň sa neukáže. Inak berie blok pod nadpisom „Denní / Polední menu / Lunch“. |
| PDF | adresa na PDF alebo odkaz na PDF typu „Obědová nabídka“ | Prečíta text PDF a vezme dnešný deň. Naskenované PDF bez textu prečíta cez OCR. |
| kotva | adresa končí `#niečo`, napríklad `#lunch-menu` | Číta len tú časť stránky, na ktorú kotva ukazuje. |
| obrázok | menu je len ako obrázok | Obrázok prečíta cez OCR (Tesseract, čeština + angličtina) a vezme z neho dnešný deň. Zvládne aj týždenné menu v dvoch stĺpcoch. Ak je na obrázku týždeň, napríklad „12.10.2026-16.10.2026“, a dnešok doňho nepatrí, menu sa neukáže. |
| podstránka | odkaz typu „Denní menu“ | Ak na hlavnej stránke menu nie je, otvorí odkaz na denné menu alebo vložený iframe. Takú stránku číta voľnejšie: cena môže byť aj číslo bez „Kč“, a keď nič nenájde, ukáže obrázok s menu alebo text stránky. Celý jedálny lístok nikdy. |

### Keď sa denné menu nenájde

Karta reštaurácie vtedy ukáže, ktoré sekcie na stránke našla. Dá sa to opraviť v `restaurants.yaml`:

```yaml
  - name: Padagali
    url: https://padagali.choiceqr.com/section:menu
    daily_section: "Lunch"        # text z názvu sekcie alebo nadpisu denného menu
```

- `daily_section` vyberie sekciu alebo nadpis, ktorý ten text obsahuje. Na veľkosti písmen a diakritike nezáleží.
- `selector` vyberie časť stránky podľa CSS selektora, napríklad `"#denni-menu"`.
- `also` pridá k dennému menu ďalšie sekcie, napríklad `also: ["pizz"]` pre ponuku pízz. Ak je sekcia rozpísaná po dňoch, ukáže sa len dnešok.

Na karte je aj odkaz *Stiahnuť HTML stránky na kontrolu*. Stiahne stránku presne tak, ako ju vidí server. Tento súbor sa hodí na opravu parsera.
Stránky, ktoré menu vykresľujú až JavaScriptom alebo ho majú len v PDF, zatiaľ nečíta.
Pri lokálnom vývoji bez Dockeru treba na čítanie obrázkov nainštalovať `tesseract-ocr` s balíčkom `tesseract-ocr-ces`. Bez neho aplikácia ukáže len odkaz na obrázok.

## Vývoj

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest
DATA_DIR=./data uvicorn app.main:app --reload
```

Premenné prostredia: `REFRESH_MINUTES` (30), `TZ` (Europe/Prague), `DATA_DIR`, `RESTAURANTS_FILE`, `DISABLE_REFRESH=1`.
