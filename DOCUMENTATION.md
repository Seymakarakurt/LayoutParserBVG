# LayoutParserBVG – Produktdokumentation

| **Produkt** | LayoutParserBVG |
| **Typ** | Lokaler Prototyp zur Document Image Analysis  |
| **Installation & Start** | siehe [README.md](README.md) |

## Inhaltsverzeichnis

1. [Über das Produkt](#1-über-das-produkt)
2. [Projektumfang (Scope)](#2-projektumfang-scope)
3. [Funktionen im Überblick](#3-funktionen-im-überblick)
4. [Anwenderleitfaden](#4-anwenderleitfaden)
5. [Technologie-Stack](#5-technologie-stack)
6. [End-to-End-Pipeline (Document Image Analysis)](#6-end-to-end-pipeline-document-image-analysis)
7. [OCR-Strategie und Datenschutz](#7-ocr-strategie-und-datenschutz)
8. [Laufzeiten und Erwartungen](#8-laufzeiten-und-erwartungen)
9. [Grenzen des Prototyps](#9-grenzen-des-prototyps)
10. [Glossar](#10-glossar)

## 1. Über das Produkt

**LayoutParserBVG** wertet gescannte historische BVG-Baupläne aus. Statt ein gesamtes Blatt abzutippen, sucht das System gezielt im Schriftfeld nach drei Angaben:

- **Stationsname**
- **Linie**
- **Plannummer**

Die Ergebnisse erscheinen in einer lokalen Oberfläche (Planarchiv). Dort können sie geprüft, korrigiert, bestätigt und als CSV oder JSON exportiert werden.

Backend und Frontend laufen auf dem eigenen Rechner. Planinhalte werden nicht an Cloud-OCR-Dienste gesendet.

## 2. Projektumfang (Scope)

### 2.1 Im Scope

- Erkennung der Schriftfeld-Bereiche für Station, Linie und Plannummer (Layout Detection)
- lokale Texterkennung mit **Tesseract**
- Ableitung der drei Metadatenfelder
- Auftragsverwaltung, Prüfung und Export in der Oberfläche
- Stapelverarbeitung mehrerer Pläne nacheinander

### 2.2 Nicht im Scope

- vollständiges Archiv- oder Dokumentenmanagementsystem
- unternehmensweite Suche über alle Bestände
- CAD-/Vektorisierung kompletter Planzeichnungen
- Anbindung externer OCR-Cloud-Dienste (Handschrift, historische Spezialfonts über Drittanbieter)
- Verarbeitung von PDF

## 3. Funktionen im Überblick

### 3.1 Kernfunktionen der Analyse

| Funktion | Beschreibung |
|----------|--------------|
| Layout Detection | Faster R-CNN erkennt Regionen `STATION_FIELD`, `LINE_FIELD`, `PLAN_NUMBER_FIELD` |
| OCR | Tesseract liest Text aus den erkannten Ausschnitten (`deu` + `eng`) |
| Extraktion | formt Stationsname, Linie und Plannummer |
| Stationsliste | optionaler Abgleich mit einer lokalen BVG-Stationenliste |
| Stapel | mehrere Dateien in einem Auftrag, Verarbeitung sequentiell |

### 3.2 Funktionen der Oberfläche (Planarchiv)

| Bereich | Was Sie tun können |
|---------|-------------------|
| Aufträge | neuen Auftrag anlegen, speichern, wieder öffnen, löschen |
| Upload | Dateien, Ordner oder ZIP (TIFF, PNG, JPEG) |
| Automatische Prüfung | Analyse über Backend (Layout → OCR → Extraktion) |
| Manuelle Prüfung | Pläne ohne Automatik öffnen und Felder selbst ausfüllen |
| Vorschau | Plan anzeigen, zoomen, drehen, bei Mehrseitenbildern blättern, Vollbild (falls Browser erlaubt) |
| Felder bearbeiten | Station, Linie, Plannummer korrigieren |
| Stationsvorschlag | Vorschlag aus der Liste annehmen oder verwerfen |
| Speichern | Zwischenstand lokal sichern |
| Bestätigen | Dokument als geprüft markieren |
| Ungeklärt | Dokument als ungelöst kennzeichnen |
| Filter | z. B. nach Prüfstatus in der Dokumentliste |
| Export | CSV oder JSON (geprüfte oder alle Dokumente) |
| Sprache | Umschaltung **Deutsch** / **English** |
| Darstellung | **Light Mode** und **Dark Mode** umschaltbar |

### 3.3 Unterstützte Dateiformate

| Format | Status |
|--------|--------|
| TIFF / TIF | unterstützt |
| PNG | unterstützt |
| JPEG / JPG | unterstützt |
| ZIP mit obigen Formaten | unterstützt |
| PDF | nicht unterstützt |

## 4. Anwenderleitfaden

Voraussetzung: Backend und Frontend laufen (siehe [README.md](README.md)). Die Oberfläche öffnet sich unter **http://127.0.0.1:8501**.

### 4.1 Orientierung in der Oberfläche

Oben sehen Sie typischerweise:

- den Auftragstitel / Arbeitsbereich
- Sprachumschaltung **English** / **Deutsch**
- den Schalter für **Dark Mode** / **Light Mode**
- den Hinweis auf den lokalen Workspace

Der Ablauf folgt vier Schritten:

1. Dateien  
2. Verarbeitung  
3. Prüfung  
4. Export  

### 4.2 Light Mode und Dark Mode

In der Kopfzeile können Sie zwischen heller und dunkler Darstellung wechseln.

- **Light Mode:** helle Oberfläche (Standardwirkung)
- **Dark Mode:** dunkle Oberfläche für längeres Arbeiten bei weniger Blendung

Die Einstellung betrifft die Bedienoberfläche, nicht die Analyse der Pläne.

### 4.3 Neuen Auftrag anlegen

1. **Neuer Auftrag** wählen.
2. Dateien per Drag-and-Drop ablegen oder Dateien / ZIP auswählen.
3. Modus wählen:
   - **Automatische Prüfung** – Backend analysiert die Pläne.
   - **Manuelle Prüfung** – Felder starten leer; Sie tragen Werte selbst ein.
4. Auftrag starten.

Bei automatischer Prüfung erscheint der Fortschritt. Bleiben Sie geduldig: einzelne Pläne können wenige Minuten oder deutlich länger brauchen (siehe [Abschnitt 8](#8-laufzeiten-und-erwartungen)).

### 4.4 Dokument prüfen

1. Auftrag zur Prüfung öffnen.
2. In der Liste ein Dokument auswählen.
3. Vorschau prüfen (Zoom, Drehen, Seite wechseln).
4. Die drei Felder kontrollieren und bei Bedarf korrigieren.
5. Falls ein **Stationsvorschlag** erscheint: annehmen oder verwerfen.
6. **Speichern**, um den Stand zu halten.
7. **Bestätigen**, wenn die Prüfung abgeschlossen ist (auch bei bewusst leeren Feldern möglich).

Nach einer Änderung an einem bereits bestätigten Dokument ist erneut zu bestätigen.

### 4.5 Exportieren

1. Export-Bereich öffnen (Schritt 4).
2. Umfang wählen (z. B. nur geprüfte Dokumente).
3. Format wählen:
   - **CSV** – drei Felder und Prüfstatus
   - **JSON** – zusätzlich Originalwerte und Kennzeichnung manueller Änderungen
4. Datei lokal speichern.

### 4.6 Aufträge verwalten

- Aufträge bleiben unter `frontend/local_jobs/` gespeichert und sind nach Neustart der Oberfläche noch da.
- Löschen entfernt den Auftrag einschließlich lokal zugehöriger Prüfdaten. Vorher exportieren, wenn die Ergebnisse benötigt werden.

### 4.7 Typischer Ablauf auf einen Blick

```text
Backend + Frontend starten
    → Neuer Auftrag + Upload
    → Automatische oder manuelle Prüfung
    → Dokumente reviewen (Felder, Vorschlag, Bestätigen)
    → CSV oder JSON exportieren
```

## 5. Technologie-Stack

| Schicht | Technologie | Rolle |
|---------|-------------|--------|
| Oberfläche | Streamlit | hostet die lokale Web-Oberfläche |
| UI | HTML, JavaScript, Tailwind (CDN) | Planarchiv: Aufträge, Prüfung, Export, Dark/Light Mode |
| API | FastAPI, Uvicorn | Upload, Job-Status, Ergebnisse auf `127.0.0.1:8000` |
| Layout Detection | PyTorch, Torchvision, Faster R-CNN | findet die Schriftfeld-Regionen |
| OCR | Tesseract (`deu` + `eng`) | liest Text aus Bildausschnitten |
| Bildverarbeitung | OpenCV, Pillow | Vorbereitung, Crops, Vorschauen |
| Extraktion | eigene Python-Logik | Ableitung von Station, Linie, Plannummer |
| Stationenabgleich | lokale JSON-Liste | Vorschläge / Normalisierung von Stationsnamen |

Alle Analyse-Schritte laufen lokal. Es gibt keine Pflicht-`.env`-Datei; optional kann `BVG_BACKEND_URL` gesetzt werden (siehe README).

## 6. End-to-End-Pipeline (Document Image Analysis)

Document Image Analysis (DIA) meint hier: Aus einem Dokument**bild** werden strukturierte Angaben gewonnen – nicht der gesamte Plantext.

### 6.1 Ablauf

```text
Planbild (Upload)
    → 1. Vorbereitung (Arbeitsbild / Skalierung)
    → 2. Layout Detection (wo stehen Station / Linie / Plannummer?)
    → 3. OCR mit Tesseract (was steht in diesen Bereichen?)
    → 4. Information Extraction (drei Felder ableiten)
    → 5. Menschliche Prüfung in der UI
    → 6. Export (CSV / JSON)
```

### 6.2 Schritt für Schritt

**1. Vorbereitung**  
Das hochgeladene Bild wird in ein standardisiertes Arbeitsformat überführt. Informationen zur Originalauflösung bleiben erhalten, damit OCR möglichst auf dem hochauflösenden Original arbeiten kann.

**2. Layout Detection**  
Ein trainiertes Faster-R-CNN-Modell markiert Kandidatenboxen für Station, Linie und Plannummer. Ausgabe sind Koordinaten und Klassen – noch kein fertiger Text. Wegen des **kleinen annotierten Datensatzes** ist die Detektion begrenzt; die **Linie** ist davon besonders stark betroffen (siehe [Abschnitt 9.1](#91-trainingsdaten-und-modellqualität)).

**3. OCR**  
Für die erkannten Boxen erzeugt das System Ausschnitte und liest sie mit Tesseract. Pro Ausschnitt können mehrere Varianten (z. B. unterschiedliche PSM-/Skalierungsoptionen) getestet werden. Das erhöht die Robustheit, verlängert aber die Laufzeit.

**4. Extraktion**  
Aus den OCR-Kandidaten werden die drei Zielwerte ausgewählt und bereinigt. Stationsnamen können gegen die lokale BVG-Liste geprüft werden; die Oberfläche kann einen Vorschlag anzeigen.

**5. Review**  
Die automatischen Werte sind Vorschläge. Verbindlich werden sie erst durch Speichern und Bestätigen in der Oberfläche.

### 6.3 Warum nicht das ganze Blatt OCR-en?

Die gesuchten Angaben stehen typischerweise im Schriftfeld. Layout Detection begrenzt die OCR auf relevante Regionen. Das spart Zeit gegenüber einer Vollblatt-OCR und reduziert Fehltreffer aus Zeichnungen und Maßketten – ohne externe Dienste.

## 7. OCR-Strategie und Datenschutz

### 7.1 Bewusste Entscheidung: nur Tesseract

Im Prototyp kommt **ausschließlich Tesseract** zum Einsatz (Sprachen Deutsch und Englisch). Es wurden bewusst **keine** zusätzlichen OCR-Module für historische Spezialschriften oder Handschrift angebunden, die Daten an **externe Dienstleister** senden würden.

### 7.2 Begründung

Die Planbilder sind **sensible, betriebsinterne Daten der BVG (Kunde)**. Eine Weitergabe an Cloud-OCR-Anbieter – auch nur zur Texterkennung – ist in diesem Kontext nicht vorgesehen und wurde deshalb ausgeschlossen.

Tesseract läuft **vollständig lokal**. Planinhalte verlassen den Rechner der betreibenden Person nicht über einen OCR-Cloud-API-Aufruf.

### 7.3 Konsequenz für die Qualität

Handschrift, stark beschädigte Schrift oder sehr ungewöhnliche historische Typografie können mit Tesseract schwieriger lesbar sein als mit spezialisierten Cloud-Lösungen. Das ist ein bewusstes Trade-off zugunsten von Datenschutz und lokaler Kontrolle. Die Oberfläche erlaubt Korrekturen durch Fachpersonen.

## 8. Laufzeiten und Erwartungen

Bitte vor dem Start größerer Aufträge beachten:

| Beobachtung | Einordnung |
|-------------|------------|
| Manche Pläne | schaffen die Pipeline in **unter 5 Minuten** |
| Andere Pläne | brauchen **über 30 Minuten** – vereinzelt deutlich länger |
| Hauptfaktor | vor allem **Pixelanzahl / Auflösung** und die Zahl der Layout-Kandidaten (OCR-Aufwand) |
| Layout Detection | typischerweise Sekunden bis niedrige Zehnerspanne Sekunden |
| OCR | zeitdominanter Schritt |

Die Verarbeitung läuft **sequentiell** (ein Plan nach dem anderen). Lange Laufzeiten bedeuten nicht automatisch einen Absturz, solange Backend und zugehörige Prozesse aktiv sind.

**Empfehlung:** Bei sehr großen TIFF-Scans mit wenigen Testplänen starten und die Laufzeit beobachten, bevor große Stapel angestoßen werden.

## 9. Grenzen des Prototyps

### 9.1 Trainingsdaten und Modellqualität

Das Layout-Modell konnte nur auf einem **sehr schmalen Datensatz** trainiert werden: Es standen vergleichsweise **wenige annotierte Pläne** zur Verfügung. Dadurch sind die erreichbare Erkennungsqualität und die Robustheit über unterschiedliche Planlayouts hinweg begrenzt.

Besonders betroffen ist die **Linie**. Im Trainingsset war das Linienfeld deutlich seltener bzw. weniger klar annotierbar als Station und Plannummer. In der Praxis fällt die automatische Linienextraktion deshalb **deutlich ungenauer** aus. Falsche oder fehlende Linienwerte sind ein bekanntes Limit dieses Prototyps. Station und Plannummer sind in der Regel zuverlässiger, aber ebenfalls nicht fehlerfrei.

Die Oberfläche sieht deshalb bewusst eine **menschliche Prüfung und Korrektur** vor – insbesondere beim Linienfeld.

### 9.2 Weitere Grenzen

- Qualitätsunterschiede zwischen Station, Linie und Plannummer hängen zusätzlich von Scanqualität und OCR ab.
- Kein SLA, kein Mehrbenutzer-Rechtekonzept, keine Hochverfügbarkeit.
- PDF wird nicht verarbeitet.
- Ohne `backend/models/layout_detector_v3.pth` keine automatische Analyse.
- Ergebnisse können bei knappen Kandidaten leicht variieren (u. a. Hardware/OCR-Ausschnitte).

## 10. Glossar

| Begriff | Bedeutung |
|---------|-----------|
| DIA | Document Image Analysis – automatisierte Auswertung von Dokumentbildern |
| Layout Detection | Finden von Regionen bestimmter Klassen im Bild |
| OCR | Optical Character Recognition – optische Zeichenerkennung |
| Tesseract | lokal laufende Open-Source-OCR-Engine |
| Schriftfeld | Bereich mit administrativen Angaben (Station, Linie, Nummer, …) |
| Auftrag | Paket aus einem oder mehreren Plänen in der Oberfläche |
| Review | menschliche Prüfung und ggf. Korrektur der Systemvorschläge |
| Light / Dark Mode | helle bzw. dunkle Darstellung der Oberfläche |
| Pipeline | verarbeitungskette von Upload bis Extraktion |

## Verweis zur Installation

Installation, virtuelle Umgebungen, optionale Umgebungsvariable `BVG_BACKEND_URL` und Start unter macOS/Windows:

→ **[README.md](README.md)**
