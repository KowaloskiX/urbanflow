# UrbanFlow

UrbanFlow to centrum operacyjne do monitorowania komunikacji miejskiej (tramwajów i autobusów) w Krakowie w czasie rzeczywistym. System integruje dane na żywo, wizualizuje je na interaktywnej mapie i wspiera decyzje dyspozytorskie.

## Architektura projektu

Projekt składa się z trzech głównych modułów:

- **Frontend (`/frontend`)**
  - Aplikacja webowa (React, Next.js/Vinext) prezentująca interaktywny panel dyspozytorski.
  - Wykorzystuje MapLibre GL JS do wizualizacji map wektorowych.
  - Odbiera dane w czasie rzeczywistym (WebSocket) i obsługuje symulacje (demo).
  
- **Backend (`/backend`)**
  - Serwer API oparty o FastAPI (Python).
  - Integruje dane GTFS-Realtime z krakowskiego ZTP.
  - Utrzymuje stan pojazdów (State Store) i rozgłasza aktualizacje do klientów podłączonych przez WebSocket.
  - Obsługuje logikę "pojazdów demo" dla celów symulacyjnych.

- **Decision Making Engine (`/DecisionMakingAlgo`)**
  - Zaawansowany moduł (algorytm) wspomagający proces decyzyjny przy zarządzaniu flotą i reakcji na incydenty w sieci komunikacyjnej.

## Uruchomienie lokalne

### Wymagania
- Node.js (dla frontendu)
- Python 3.10+ (dla backendu)
- [uv](https://github.com/astral-sh/uv) (menedżer pakietów Python) lub pip
- Docker & Docker Compose (opcjonalnie, do konteneryzacji)

### Szybki start (Docker)
Wystarczy użyć pliku `docker-compose.yml`, aby podnieść całe środowisko:
```bash
docker compose up -d
```
Aplikacja będzie dostępna pod adresem: `http://localhost:5173`

### Uruchomienie ręczne

**Backend:**
```bash
cd backend
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

## Liczniki pasażerów (`/counter`)

Kamera nad drzwiami wykrywa ludzi (RT-DETR z Hugging Face, licencja Apache-2.0), śledzi ich
między klatkami i liczy przejścia przez linię w progu. Wynik leci do backendu jako
**delty** — ktoś wsiadł, ktoś wysiadł — a backend sumuje je w zajętość pojazdu. To pierwsza
realna implementacja `OccupancyProvider`, który wcześniej był tylko interfejsem.

Dlaczego RT-DETR, a nie YOLO: Ultralytics YOLO jest na licencji **AGPL-3.0**, co w produkcie
oznacza otwarcie kodu albo płatną licencję.

### Jak to przetestować

```bash
# 1. Backend z pojazdem demo (linia 16, id 2184)
cd backend
SEED_FIXTURES=true REALTIME_ENABLED=false uv run uvicorn app.main:app --port 8000

# 2. Klucz dla licznika — wypisany raz, w pliku zostaje tylko hash.
#    Działający backend łapie nowe urządzenie bez restartu.
uv run python -m scripts.provision_device --vehicle-id 2184

# 3. Licznik (pierwszy raz: uv sync --extra ml)
cd ../counter
uv run count-doorway --source 0 --preview --torch-device mps --device-key tbn_...
```

`--source 0` / `1` to kamery (na Macu iPhone przez Continuity Camera i wbudowana),
`--source plik.mp4` to nagranie. `--preview` pokazuje ramki i linię, `--no-post` uruchamia
sam model bez wysyłania czegokolwiek. Na Macu zawsze `--torch-device mps` — 15 fps zamiast 4.

Dashboard (`frontend`) nie wymaga zmian: dostaje `vehicle.updated` po WebSockecie i pokazuje
zapełnienie tak jak dla danych z demo.

Z prawdziwym feedem GTFS (`REALTIME_ENABLED=true`) id pojazdów mają postać
`ztp-tram:<numer>` — klucz wydaje się dla takiego id.

### Co się dzieje w backendzie

- `POST /api/v1/ingest/passages` — partia zdarzeń z licznika, idempotentna po `eventId`:
  ponownie wysłana partia nie zmienia liczby.
- `POST /api/v1/ingest/anchor` — bezwzględna liczba pasażerów; na pętli prawda to zero,
  niezależnie od tego, ile naliczyły delty.
- Zajętość jest **nakładana** na pojazdy z GTFS przy każdym odświeżeniu. Feed nie niesie
  zapełnienia, więc bez tego każdy odczyt znikałby po 5 sekundach.
- Po każdym pomiarze uruchamia się silnik decyzyjny — wcześniej działał tylko dla
  scenariuszy demo. Najwyżej jedna otwarta rekomendacja na linię i kierunek.
- Odczyt starszy niż 180 s (`OCCUPANCY_STALE_SECONDS`) nie jest pokazywany jako aktualny.

### Znane ograniczenia (PoC)

- **Stan w pamięci.** Restart backendu zeruje liczniki i zapomina widziane `eventId`.
- **Headway i dostępność rezerwy są stałymi** (`LIVE_ASSUMED_*` w `state_store.py`) — to
  miejsce na lepsze heurystyki wysyłania tramwajów.
- **`OCCUPANCY_CONFIDENCE=0.9` jest zadeklarowane, nie zmierzone.** Licznik nie podaje
  pewności; trzeba ją wyznaczyć porównując z ręcznym liczeniem.
- **Model widział tylko wagi z COCO.** Detekcja z góry działa przy testach przy biurku, ale
  skuteczność na prawdziwych drzwiach tramwaju nie jest zmierzona.
- Kilka drzwi: osobny licznik i klucz na każde drzwi, wszystkie z tym samym
  `--vehicle-id`. Piszą do wspólnej sumy pojazdu; `eventId` zawiera nazwę drzwi
  (`--door front|middle|rear`), więc zdarzenia z różnych drzwi się nie zderzają.

## Identyfikacja wizualna
Materiały graficzne i logotypy projektu znajdują się w folderze `/Identification `.
