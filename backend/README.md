# UrbanFlow API

UrbanFlow to backend systemu wspomagania dyspozytora komunikacji miejskiej.
Łączy stan pojazdów z informacją o zapełnieniu, wykrywa utrzymujące się
przeciążenie i pozwala zasymulować wysłanie dodatkowego tramwaju.

Aktualna wersja jest pierwszym działającym pionowym wycinkiem MVP. Działa w
trybie `DEMO`, przechowuje stan w pamięci i udostępnia komplet podstawowych
kontraktów HTTP oraz WebSocket potrzebnych frontendowi.

## Co już działa

- API FastAPI pod prefiksem `/api/v1`,
- dokumentacja OpenAPI i Swagger UI,
- lista pojazdów z filtrowaniem,
- szczegóły i historia pojazdu,
- lista linii i geometria trasy w GeoJSON,
- cztery deterministyczne scenariusze demonstracyjne,
- regułowe wykrywanie trwałego przeciążenia,
- tworzenie, pobieranie i odrzucanie rekomendacji,
- symulowane wysłanie dodatkowego tramwaju,
- ruch `SIM-TRAM-01` po geometrii trasy,
- anulowanie i reset symulacji,
- aktualizacje przez WebSocket,
- CORS konfigurowany adresem frontendu,
- testy głównego przepływu demonstracyjnego.

Na tym etapie pozycje i trasy są danymi demonstracyjnymi. Interfejsy pod
GTFS-Realtime i Occupancy API są przygotowane, ale prawdziwe źródła nie są
jeszcze podłączone. Stan znika po restarcie procesu, ponieważ SQLite będzie
dodany w kolejnym etapie.

## Technologie

- Python 3.12+
- FastAPI
- Pydantic 2
- Uvicorn
- Pytest
- Docker Compose

## Szybki start

Poniższe polecenia uruchom z głównego katalogu repozytorium.

### Opcja 1: `uv`

```bash
cd backend
uv sync --extra dev
uv run uvicorn app.main:app --reload
```

### Opcja 2: standardowy `venv` i `pip`

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload
```

Po uruchomieniu dostępne są:

| Adres | Zastosowanie |
|---|---|
| <http://localhost:8000/docs> | interaktywna dokumentacja Swagger UI |
| <http://localhost:8000/redoc> | dokumentacja ReDoc |
| <http://localhost:8000/openapi.json> | specyfikacja OpenAPI w JSON |
| <http://localhost:8000/api/v1/health> | stan backendu i źródeł |
| `ws://localhost:8000/api/v1/live` | aktualizacje WebSocket |

### Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

Compose uruchamia cały pionowy wycinek: dashboard pod
<http://localhost:5173> oraz API pod <http://localhost:8000>.

## Konfiguracja

Zmienne środowiskowe można umieścić w pliku `.env` w katalogu głównym.

| Zmienna | Domyślna wartość | Znaczenie |
|---|---|---|
| `APP_MODE` | `DEMO` | tryb pracy; scenariusze i reset wymagają `DEMO` |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | origin dopuszczony przez CORS |
| `VITE_API_BASE_URL` | `http://localhost:8000/api/v1` | publiczny adres API używany przez dashboard |
| `SITE_URL` | `http://localhost:5173` | bazowy adres metadanych frontendu |

Przykład znajduje się w pliku [`../.env.example`](../.env.example).

## Zasady API

- Wszystkie endpointy biznesowe mają prefiks `/api/v1`.
- JSON używa nazw pól w `camelCase`, np. `vehicleId` i `loadFactor`.
- Daty zwracane są jako ISO 8601 w UTC, np. `2026-09-06T13:24:12Z`.
- `loadFactor` jest ułamkiem: `0.94` oznacza 94% zapełnienia.
- Pojazd symulowany ma zawsze `isSimulation: true`,
  `source: "SIMULATOR"` i `freshness: "SIMULATION"`.
- Brak uwierzytelniania jest świadomym uproszczeniem wersji demo.

## Lista endpointów

| Metoda | Endpoint | Działanie |
|---|---|---|
| `GET` | `/api/v1/health` | zwraca tryb aplikacji i stan źródeł |
| `GET` | `/api/v1/vehicles` | zwraca i filtruje bieżące pojazdy |
| `GET` | `/api/v1/vehicles/{vehicle_id}` | zwraca pojazd, historię i trasę |
| `GET` | `/api/v1/vehicles/{vehicle_id}/history` | zwraca historię do 60 minut |
| `GET` | `/api/v1/routes` | zwraca linie i liczbę ich pojazdów |
| `GET` | `/api/v1/routes/{route_id}/shape` | zwraca geometrię linii w GeoJSON |
| `GET` | `/api/v1/recommendations` | zwraca rekomendacje |
| `GET` | `/api/v1/recommendations/{recommendation_id}` | zwraca rekomendację |
| `POST` | `/api/v1/recommendations/{recommendation_id}/dismiss` | odrzuca rekomendację |
| `POST` | `/api/v1/mock-dispatch/extra-trams` | tworzy symulowany tramwaj |
| `GET` | `/api/v1/mock-dispatch/extra-trams` | zwraca wszystkie dispatch'e |
| `POST` | `/api/v1/mock-dispatch/extra-trams/{dispatch_id}/cancel` | anuluje dispatch |
| `POST` | `/api/v1/mock-dispatch/reset` | resetuje stan demo |
| `GET` | `/api/v1/demo/scenarios` | zwraca scenariusze demo |
| `POST` | `/api/v1/demo/scenarios/{scenario_id}/activate` | aktywuje scenariusz |
| `WS` | `/api/v1/live` | publikuje zdarzenia na żywo |

## Szczegóły endpointów

### Stan aplikacji

#### `GET /api/v1/health`

Sprawdza, czy backend działa, w jakim jest trybie i jaki jest stan źródeł.

```bash
curl http://localhost:8000/api/v1/health
```

Odpowiedź `200 OK`:

```json
{
  "status": "ok",
  "mode": "DEMO",
  "sources": {
    "gtfsStatic": "ok",
    "gtfsRealtime": "ok",
    "occupancy": "ok"
  },
  "lastRealtimeUpdate": "2026-09-06T13:24:12Z"
}
```

### Pojazdy

#### `GET /api/v1/vehicles`

Zwraca aktualny stan pojazdów. Parametry można ze sobą łączyć.

| Parametr | Typ | Domyślnie | Znaczenie |
|---|---|---:|---|
| `routeId` | string | brak | linia, np. `route-16` |
| `occupancyStatus` | enum | brak | status zapełnienia |
| `freshness` | enum | brak | świeżość danych |
| `includeSimulation` | boolean | `true` | czy dołączyć symulacje |
| `bbox` | string | brak | `minLon,minLat,maxLon,maxLat` |

Dozwolone statusy zapełnienia: `UNKNOWN`, `LOW`, `MODERATE`, `BUSY`,
`CROWDED`, `OVER_CAPACITY`. Dozwolona świeżość: `LIVE`, `STALE`, `OFFLINE`,
`SIMULATION`.

```bash
curl 'http://localhost:8000/api/v1/vehicles?routeId=route-16&includeSimulation=false'
```

Odpowiedź:

```json
{
  "generatedAt": "2026-09-06T13:24:12Z",
  "vehicles": [],
  "sourceHealth": {
    "gtfsRealtime": "LIVE",
    "occupancy": "LIVE"
  }
}
```

Niepoprawny format `bbox` zwraca `400 Bad Request`.

#### `GET /api/v1/vehicles/{vehicle_id}`

Zwraca:

- `vehicle` — pełny bieżący `VehicleState`,
- `history` — pomiary z ostatnich 30 minut,
- `route` — geometria trasy w formacie GeoJSON.

```bash
curl http://localhost:8000/api/v1/vehicles/2184
```

Nieznany pojazd zwraca `404 Not Found`.

#### `GET /api/v1/vehicles/{vehicle_id}/history`

Zwraca serię pozycji, zapełnienia i opóźnienia.

| Parametr | Typ | Zakres | Domyślnie |
|---|---|---:|---:|
| `minutes` | integer | 1–60 | 30 |

```bash
curl 'http://localhost:8000/api/v1/vehicles/2184/history?minutes=15'
```

Punkt historii:

```json
{
  "measuredAt": "2026-09-06T13:24:10Z",
  "latitude": 50.0635,
  "longitude": 19.9452,
  "loadFactor": 0.94,
  "delaySeconds": 165
}
```

### Linie i geometrie

#### `GET /api/v1/routes`

Zwraca znane linie. `vehicleCount` jest obliczane na podstawie aktualnego
stanu i uwzględnia również tramwaj symulowany.

```bash
curl http://localhost:8000/api/v1/routes
```

```json
[
  {
    "routeId": "route-16",
    "shortName": "16",
    "longName": "Mistrzejowice – Borek Fałęcki",
    "color": "D42127",
    "vehicleCount": 1
  }
]
```

#### `GET /api/v1/routes/{route_id}/shape`

Zwraca `Feature` GeoJSON z geometrią `LineString`.

| Parametr | Typ | Zakres | Domyślnie |
|---|---|---:|---:|
| `directionId` | integer | 0–1 | 0 |

Dla demonstracyjnej linii 16 dostępny jest kierunek `1`:

```bash
curl 'http://localhost:8000/api/v1/routes/route-16/shape?directionId=1'
```

```json
{
  "type": "Feature",
  "geometry": {
    "type": "LineString",
    "coordinates": [[19.935, 50.067], [19.941, 50.0645]]
  },
  "properties": {
    "routeId": "route-16",
    "directionId": 1
  }
}
```

Nieznana para linia–kierunek zwraca `404 Not Found`.

### Scenariusze demonstracyjne

#### `GET /api/v1/demo/scenarios`

Zwraca scenariusze i informację, który jest aktywny.

| Identyfikator | Rezultat |
|---|---|
| `overload-line-16` | przeciążenie i otwarta rekomendacja |
| `sensor-offline` | stary pomiar, brak rekomendacji |
| `no-reserve-available` | przeciążenie bez możliwej interwencji |
| `successful-intervention` | rekomendacja gotowa do symulacji |

```bash
curl http://localhost:8000/api/v1/demo/scenarios
```

#### `POST /api/v1/demo/scenarios/{scenario_id}/activate`

Resetuje poprzedni stan demo, ustawia dane wybranego scenariusza, uruchamia
silnik decyzji i publikuje zdarzenia WebSocket.

```bash
curl -X POST \
  http://localhost:8000/api/v1/demo/scenarios/successful-intervention/activate
```

```json
{
  "scenario": {
    "id": "successful-intervention",
    "name": "Udana interwencja",
    "description": "Pełny scenariusz rekomendacji i symulacji.",
    "active": true
  },
  "targetVehicleId": "2184",
  "recommendationId": "rec-16-1-1788697560"
}
```

Endpoint działa tylko przy `APP_MODE=DEMO`. W innym trybie zwraca `403`.

### Rekomendacje

Rekomendacja powstaje tylko wtedy, gdy jednocześnie:

- zapełnienie wynosi co najmniej 85%,
- kolejne wysokie pomiary obejmują co najmniej 120 sekund,
- pewność pomiaru wynosi co najmniej 75%,
- dane są świeże,
- odstęp do następnego pojazdu wynosi co najmniej 420 sekund,
- dostępny jest tramwaj rezerwowy.

#### `GET /api/v1/recommendations`

Opcjonalny parametr `status` przyjmuje `OPEN`, `ACCEPTED` lub `DISMISSED`.

```bash
curl 'http://localhost:8000/api/v1/recommendations?status=OPEN'
```

#### `GET /api/v1/recommendations/{recommendation_id}`

Zwraca pełne uzasadnienie, proponowane działanie i oczekiwany wpływ.

```bash
curl http://localhost:8000/api/v1/recommendations/RECOMMENDATION_ID
```

Najważniejsze sekcje:

- `segment` — odcinek, którego dotyczy problem,
- `reason` — zapełnienie, czas trwania, headway i pewność,
- `proposedAction` — parametry dodatkowego tramwaju,
- `expectedImpact` — estymowane KPI po interwencji.

#### `POST /api/v1/recommendations/{recommendation_id}/dismiss`

Odrzuca rekomendację i zapisuje powód.

```bash
curl -X POST \
  http://localhost:8000/api/v1/recommendations/RECOMMENDATION_ID/dismiss \
  -H 'Content-Type: application/json' \
  -d '{"reason":"Brak dostępnego motorniczego"}'
```

Po operacji rekomendacja ma status `DISMISSED`.

### Symulowany dispatch

#### `POST /api/v1/mock-dispatch/extra-trams`

Akceptuje otwartą rekomendację i tworzy symulowany dodatkowy tramwaj.

```bash
curl -X POST http://localhost:8000/api/v1/mock-dispatch/extra-trams \
  -H 'Content-Type: application/json' \
  -d '{
    "recommendationId": "RECOMMENDATION_ID",
    "routeId": "route-16",
    "directionId": 1,
    "startStopId": "stop-3012",
    "endStopId": "stop-3078",
    "capacity": 202,
    "departureDelaySeconds": 0,
    "simulationSpeed": 20
  }'
```

Odpowiedź `201 Created`:

```json
{
  "dispatchId": "dispatch-001",
  "recommendationId": "RECOMMENDATION_ID",
  "vehicleId": "SIM-TRAM-01",
  "routeId": "route-16",
  "directionId": 1,
  "startStopId": "stop-3012",
  "endStopId": "stop-3078",
  "capacity": 202,
  "status": "DISPATCHED",
  "isSimulation": true,
  "simulationSpeed": 20,
  "createdAt": "2026-09-06T13:26:20Z",
  "estimatedStartAt": "2026-09-06T13:26:20Z"
}
```

`simulationSpeed=20` oznacza, że jedna sekunda rzeczywista odpowiada 20
sekundom symulacji. Przejazd ma 900 sekund czasu symulowanego. Backend
aktualizuje pozycję raz na sekundę.

Statusy dispatchu:

```text
DISPATCHED → WAITING_FOR_DEPARTURE → IN_SERVICE → COMPLETED
                                      ↓
                                  CANCELLED
```

Użycie rekomendacji, która nie jest otwarta, zwraca `409 Conflict`.
Nieznana rekomendacja, linia lub geometria zwraca `404 Not Found`.

#### `GET /api/v1/mock-dispatch/extra-trams`

Zwraca wszystkie aktywne, zakończone i anulowane dispatch'e.

```bash
curl http://localhost:8000/api/v1/mock-dispatch/extra-trams
```

#### `POST /api/v1/mock-dispatch/extra-trams/{dispatch_id}/cancel`

Ustawia status `CANCELLED` i usuwa odpowiadający pojazd symulowany z listy.
Zakończonego dispatchu nie można anulować.

```bash
curl -X POST \
  http://localhost:8000/api/v1/mock-dispatch/extra-trams/dispatch-001/cancel
```

#### `POST /api/v1/mock-dispatch/reset`

Usuwa rekomendacje, dispatch'e, historię scenariusza i pojazdy symulowane, a
następnie odtwarza początkowe dane demo.

```bash
curl -X POST http://localhost:8000/api/v1/mock-dispatch/reset
```

Endpoint jest dostępny wyłącznie w trybie `DEMO`.

### WebSocket

#### `WS /api/v1/live`

Po połączeniu serwer wysyła:

```json
{
  "type": "connected",
  "payload": {"status": "ok"}
}
```

Następnie publikuje:

| Typ | Kiedy powstaje |
|---|---|
| `vehicle.updated` | aktywacja scenariusza, utworzenie lub ruch symulacji |
| `recommendation.created` | scenariusz tworzy rekomendację |
| `recommendation.updated` | rekomendacja zostaje odrzucona |
| `dispatch.status_changed` | dispatch zostaje utworzony lub anulowany |

Minimalny przykład w JavaScript:

```javascript
const socket = new WebSocket("ws://localhost:8000/api/v1/live");

socket.onmessage = (event) => {
  const message = JSON.parse(event.data);
  console.log(message.type, message.payload);
};
```

Klient powinien utrzymywać połączenie otwarte. Może wysyłać tekst jako
heartbeat; jego treść jest obecnie ignorowana.

## Model `VehicleState`

Prawdziwy i symulowany tramwaj korzystają z tego samego modelu.

| Pole | Znaczenie |
|---|---|
| `vehicleId` | stabilny identyfikator pojazdu |
| `tripId` | identyfikator kursu |
| `routeId`, `routeShortName` | identyfikator i numer linii |
| `headsign`, `directionId` | kierunek i nazwa krańcówki |
| `latitude`, `longitude` | bieżąca pozycja |
| `bearing`, `speedMps` | kierunek ruchu i prędkość |
| `currentStopSequence` | pozycja w sekwencji przystanków |
| `nextStopId`, `nextStopName` | następny przystanek |
| `delaySeconds` | opóźnienie w sekundach |
| `passengerCount`, `capacity` | liczba pasażerów i pojemność |
| `loadFactor` | zapełnienie jako ułamek |
| `occupancyConfidence` | pewność pomiaru od 0 do 1 |
| `occupancyStatus` | tekstowy status zapełnienia |
| `positionMeasuredAt` | czas pomiaru pozycji |
| `occupancyMeasuredAt` | czas pomiaru zapełnienia |
| `updatedAt` | czas ostatniej zmiany stanu |
| `freshness` | świeżość lub oznaczenie symulacji |
| `source` | źródło danych |
| `isSimulation` | jednoznaczne oznaczenie symulacji |

Status zapełnienia:

| `loadFactor` | Status |
|---:|---|
| brak | `UNKNOWN` |
| poniżej 0.50 | `LOW` |
| 0.50–0.69 | `MODERATE` |
| 0.70–0.84 | `BUSY` |
| 0.85–0.99 | `CROWDED` |
| co najmniej 1.00 | `OVER_CAPACITY` |

## Pełny scenariusz demo

Poniższe polecenia wymagają uruchomionego backendu i narzędzia `jq`.

```bash
ACTIVATION=$(curl -s -X POST \
  http://localhost:8000/api/v1/demo/scenarios/successful-intervention/activate)

RECOMMENDATION_ID=$(printf '%s' "$ACTIVATION" | jq -r '.recommendationId')

curl -s 'http://localhost:8000/api/v1/recommendations?status=OPEN' | jq

curl -s -X POST http://localhost:8000/api/v1/mock-dispatch/extra-trams \
  -H 'Content-Type: application/json' \
  -d "{\
    \"recommendationId\": \"$RECOMMENDATION_ID\",\
    \"routeId\": \"route-16\",\
    \"directionId\": 1,\
    \"startStopId\": \"stop-3012\",\
    \"endStopId\": \"stop-3078\",\
    \"capacity\": 202,\
    \"departureDelaySeconds\": 0,\
    \"simulationSpeed\": 20\
  }" | jq

curl -s 'http://localhost:8000/api/v1/vehicles?routeId=route-16' | jq
```

Ostatnia odpowiedź zawiera pojazd `2184` i symulowany `SIM-TRAM-01`.

## Błędy HTTP

| Kod | Znaczenie w UrbanFlow |
|---:|---|
| `400` | niepoprawny parametr, np. `bbox` |
| `403` | użycie funkcji demo poza trybem `DEMO` |
| `404` | nieznany zasób |
| `409` | konflikt stanu, np. ponowne użycie rekomendacji |
| `422` | dane wejściowe nie spełniają modelu Pydantic |

Standardowy błąd:

```json
{
  "detail": "Vehicle not found"
}
```

## Testy i jakość kodu

```bash
cd backend
uv run pytest -q
uvx ruff check app tests
uvx ruff format --check app tests
```

Testy pokrywają health check, filtry, `bbox`, GeoJSON, WebSocket, reguły
przeciążenia oraz pełny przepływ scenariusz → rekomendacja → dispatch →
`SIM-TRAM-01`.

## Struktura projektu

```text
UrbanFlow/
├── UrbanFlow_IMPLEMENTATION_PLAN.md
├── docker-compose.yml
├── .env.example
└── backend/
    ├── README.md
    ├── Dockerfile
    ├── pyproject.toml
    ├── uv.lock
    ├── app/
    │   ├── main.py                 # FastAPI i pętla symulacji
    │   ├── config.py               # zmienne środowiskowe
    │   ├── api/                    # HTTP i WebSocket
    │   ├── domain/                 # modele Pydantic
    │   ├── integrations/           # interfejsy źródeł
    │   └── services/               # store, reguły, symulacja
    └── tests/
```

## Następne etapy

1. Import prawdziwego GTFS Static i geometrii tras.
2. Polling GTFS-Realtime z timeoutem, retry i cache.
3. Osobny `mock-occupancy-api` i adapter HTTP `OccupancyProvider`.
4. SQLite dla historii, rekomendacji i dispatchy.
5. Dokładniejszy model KPI przed i po interwencji.
6. Autoryzacja operacji dyspozytorskich i audyt.
7. Frontend React z mapą MapLibre.

Pełny plan znajduje się w
[`../UrbanFlow_IMPLEMENTATION_PLAN.md`](../UrbanFlow_IMPLEMENTATION_PLAN.md).
