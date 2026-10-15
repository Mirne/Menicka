# Menučka

Stránka, ktorá zbiera denné menu z reštaurácií, ktoré zadáte, a ukazuje, kto kam ide na obed.

- **Menu**: pre každú reštauráciu sa stiahne dnešné menu (pri štarte, potom každých 30 minút, alebo tlačidlom *Obnoviť menu*).
- **Ľudia**: zadáš meno a vyberieš reštiku (aj s poznámkou, napr. „o 11:45“). Jeden hlas na osobu a deň, ďalší ho prepíše. Hlasy sa na druhý deň začínajú odznova.
- **Reštaurácie**: v súbore `restaurants.yaml`, alebo cez sekciu *Reštaurácie* dole na stránke.

## Spustenie

```bash
./start.sh
```

Skript zostaví image, nájde voľný port od 47823 vyššie a vypíše adresu, napríklad <http://localhost:47823>.
Zvolený port uloží do `.env`, takže `docker compose up`, `restart` aj `down` potom používajú ten istý.
Konkrétny port: `PORT=51234 ./start.sh`.

Bez skriptu, napríklad na Windows bez bashu: `docker compose up --build`, s portom `PORT=51234 docker compose up --build`.

Logy: `docker compose logs -f`. Zastavenie: `docker compose down`.
Dáta, teda reštaurácie pridané na stránke a hlasy, sú v Docker volume `menicka-data`.

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

Po úprave stačí `docker compose restart`.

### Ako sa menu číta

| Typ | Kedy | Ako |
|---|---|---|
| `choiceqr` | adresa na `choiceqr.com` | Z JSON dát stránky (`__NEXT_DATA__`) vytiahne položky s názvom a cenou a ich sekcie. |
| `html` | všetko ostatné | Ak stránka vypisuje menu po dňoch (Pondělí, Úterý…), vezme dnešný deň. Inak blok pod nadpisom „Denní / Polední menu / Lunch“. Inak všetky riadky s cenou. Ak nič nenájde, skúsi odkaz „Denní menu“ na tom istom webe. |

Denné menu sa zobrazuje predvolene, celé menu sa zapne prepínačom *Zobraziť celé menu*.
Keď parser na konkrétnej stránke netrafí, najrýchlejšia oprava je doplniť `selector`.
Stránky, ktoré menu vykresľujú až JavaScriptom, alebo ho majú len ako obrázok/PDF, zatiaľ nečíta. Pri nich ukáže aspoň odkaz.

## Vývoj

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest
DATA_DIR=./data uvicorn app.main:app --reload
```

Premenné prostredia: `REFRESH_MINUTES` (30), `TZ` (Europe/Prague), `DATA_DIR`, `RESTAURANTS_FILE`, `DISABLE_REFRESH=1`.
