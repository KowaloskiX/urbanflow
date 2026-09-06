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

## Identyfikacja wizualna
Materiały graficzne i logotypy projektu znajdują się w folderze `/Identification `.
