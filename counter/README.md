# Licznik pasażerów

Program działający przy kamerze w tramwaju. Wykrywa ludzi, śledzi ich między klatkami i liczy
przejścia przez linię w progu drzwi. Do backendu wysyła tylko zdarzenia „wsiadł” i „wysiadł”,
nigdy obraz.

```
kamera → RT-DETR (osoby) → tracker IoU → przejście przez linię → partie zdarzeń → POST /ingest/passages
```

## Instalacja

```bash
uv sync                 # logika liczenia i testy, bez modelu
uv sync --extra ml      # + PyTorch, transformers i OpenCV (kilka GB), potrzebne do kamery
```

Model to [RT-DETR](https://huggingface.co/PekingU/rtdetr_r18vd_coco_o365) na licencji
Apache-2.0. Nie używamy Ultralytics YOLO, bo jego licencja AGPL-3.0 obejmowałaby cały produkt.

## Uruchomienie

```bash
# klucz urządzenia dla tramwaju (z katalogu backend/, wypisany tylko raz)
uv run python -m scripts.provision_device --vehicle-id ztp-tram:326

# licznik z kamerą laptopa i podglądem
uv run count-doorway --source 0 --preview --torch-device mps --device-key tbn_...

# sam model na nagraniu, bez wysyłania czegokolwiek
uv run count-doorway --source nagranie.mp4 --preview --no-post
```

| Opcja | Domyślnie | Opis |
|---|---|---|
| `--source` | `0` | Numer kamery albo ścieżka do nagrania. Na Macu `0` to często iPhone (Continuity Camera), `1` kamera wbudowana. |
| `--device-key` | — | Klucz urządzenia z `provision_device`; wyznacza, do którego pojazdu trafiają dane. |
| `--api-url` | `http://localhost:8000/api/v1` | Adres backendu. |
| `--line` | środek kadru | Linia liczenia `x1,y1,x2,y2` w pikselach. |
| `--inside-sign` | `1` | Która strona linii to wnętrze pojazdu; `-1` odwraca kierunek. |
| `--door` | `front` | Nazwa drzwi; kilka liczników w jednym pojeździe sumuje się w backendzie. |
| `--preview` / `--no-preview` | wyłączony | Okno z ramkami, linią i licznikiem (`q` zamyka). |
| `--post` / `--no-post` | włączony | Wysyłanie zdarzeń do backendu. |
| `--torch-device` | `cpu` | `mps` na Macu z Apple Silicon (około 66 ms na klatkę zamiast 250 ms), `cuda` na karcie NVIDIA. |
| `--threshold` | `0.5` | Minimalna pewność wykrycia. |
| `--frame-stride` | `2` | Analizuj co N-tą klatkę. |

Linię i `--inside-sign` najłatwiej ustawić z włączonym `--preview`: strzałka na podglądzie
musi wskazywać wnętrze pojazdu.

## Jak liczy

- **Tracker** dopasowuje ramki między klatkami po pokryciu i krótko przewiduje ruch osoby
  zasłoniętej przez innych pasażerów.
- **Przejście liczy się raz na osobę.** Ktoś, kto stoi w drzwiach i kołysze się nad linią,
  nie nabija licznika.
- **Linia ma długość.** Przejście poza jej końcami, na przykład przechodzień na peronie,
  się nie liczy.
- **Wysyłka jest odporna na brak zasięgu.** Zdarzenia czekają w buforze; każde ma `eventId`,
  więc ponowne wysłanie tej samej partii nie zmienia liczby w backendzie.

## Testy

```bash
uv run pytest
```

Testy sprawdzają geometrię linii, tracker i wysyłkę zdarzeń, bez modelu i bez kamery.
