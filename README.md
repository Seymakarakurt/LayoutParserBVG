# LayoutParserBVG

Lokaler Prototyp zur Auswertung historischer BVG-Baupläne (Layout-Erkennung, OCR, Prüfung und Export).

Ausführliche Projektbeschreibung: **[DOCUMENTATION.md](DOCUMENTATION.md)**

## Inhaltsverzeichnis

- [Voraussetzungen](#voraussetzungen)
- [Projekt vorbereiten](#projekt-vorbereiten)
- [Virtuelle Umgebungen (venv)](#virtuelle-umgebungen-venv)
- [Umgebungsvariablen (env)](#umgebungsvariablen-env)
- [Installation – macOS](#installation--macos)
- [Installation – Windows](#installation--windows)
- [Starten – macOS](#starten--macos)
- [Starten – Windows](#starten--windows)
- [Prüfen](#prüfen)
- [Beenden](#beenden)

## Voraussetzungen

|   Voraussetzung   |                                   Hinweis                                         |
|-------------------|-----------------------------------------------------------------------------------|
| Python **3.11**   | empfohlen                                                                         |
| **Tesseract OCR** | mit Sprachpaketen `deu` und `eng`                                                 |
| Internetzugang    | einmalig für Tailwind-CDN in der Oberfläche (Planbilder werden lokal verarbeitet) |
| Modelldatei       | `backend/models/layout_detector_v3.pth` muss vorhanden sein                       |

Ohne die Modelldatei startet die Oberfläche, die automatische Analyse funktioniert dann aber nicht.

## Projekt vorbereiten

1. Projektordner entpacken bzw. klonen.
2. Im Terminal in den Projektordner wechseln:

```bash
cd LayoutParserBVG
```

## Virtuelle Umgebungen (venv)

Backend und Frontend haben **jeweils eine eigene** virtuelle Umgebung (`.venv`).

- Die Ordner `.venv` gehören **nicht** zur Abgabe und werden lokal neu angelegt.
- Eine `.env`-Datei ist **nicht** nötig.

## Umgebungsvariablen (env)

|     Variable      | Pflicht? |         Standard        |              Bedeutung                |
|-------------------|----------|-------------------------|---------------------------------------|
| `BVG_BACKEND_URL` | nein     | `http://127.0.0.1:8000` | Adresse des Backends für das Frontend |

Bei dem Start wie unten beschrieben musst du **nichts** setzen.  
Nur setzen, wenn das Backend auf einem anderen Port läuft (im Frontend-Terminal **vor** dem Start von Streamlit).

Erlaubt sind nur lokale Adressen (`127.0.0.1` oder `localhost`).

## Installation – macOS

### 1. Tesseract installieren

```bash
brew install tesseract tesseract-lang
tesseract --version
tesseract --list-langs
```

In der Liste müssen `deu` und `eng` stehen.

### 2. Backend installieren

```bash
cd backend
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cd ..
```

### 3. Frontend installieren

```bash
cd frontend
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-frontend.txt
cd ..
```

## Installation – Windows

### 1. Tesseract installieren

1. Installer von [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki) herunterladen.
2. Beim Setup die Sprachen **Deutsch** und **Englisch** auswählen.
3. Prüfen, ob `tesseract` im Terminal/PowerShell gefunden wird:

```powershell
tesseract --version
tesseract --list-langs
```

### 2. Backend installieren

```powershell
cd backend
python3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..
```

### 3. Frontend installieren

```powershell
cd frontend
python3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-frontend.txt
cd ..
```

## Starten – macOS

Zwei Terminalfenster öffnen. **Zuerst Backend**, dann Frontend.

### Terminal 1 – Backend

```bash
cd backend
.venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

### Terminal 2 – Frontend

```bash
cd frontend
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1
```

Optional (nur bei abweichendem Backend-Port), im Frontend-Terminal **vor** Streamlit:

```bash
export BVG_BACKEND_URL="http://127.0.0.1:8000"
```

## Starten – Windows

Zwei Terminalfenster öffnen. **Zuerst Backend**, dann Frontend.

### Terminal 1 – Backend

```powershell
cd backend
.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

### Terminal 2 – Frontend

```powershell
cd frontend
.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

Optional (nur bei abweichendem Backend-Port), im Frontend-Terminal **vor** Streamlit:

```powershell
$env:BVG_BACKEND_URL="http://127.0.0.1:8000"
```

## Prüfen

| Dienst |              Adresse                 |
|--------|--------------------------------------|
| Frontend (Oberfläche) | http://127.0.0.1:8501 |
| Backend (API) | http://127.0.0.1:8000         |

Beide Terminals während der Nutzung **offen** lassen.

## Beenden

In jedem Terminal `Ctrl+C` drücken.

Ist Port 8000 oder 8501 belegt, läuft noch eine alte Sitzung – diese beenden und den Startbefehl erneut ausführen.

## Weitere Informationen

Produktbeschreibung, Architektur, Bedienung und Features: **[DOCUMENTATION.md](DOCUMENTATION.md)**
