# Food Planer

Meal Planning App mit Spoonacular API + Claude AI Integration.

## Features

- **Rezeptsuche**: Suche nach Rezepten basierend auf Zutaten oder Gelüsten
- **Claude AI**: Smarte Rezeptvorschläge die komplexe Anfragen verstehen
- **Instagram Import**: Rezepte aus Instagram Posts extrahieren
- **Wochenplan**: Kanban-Board mit Drag & Drop
- **Kalorien-Tracking**: 1800 kcal Tagesziel
- **Einkaufsliste**: Automatisch generiert aus dem Wochenplan

## Voraussetzungen

- Docker & Docker Compose
- Spoonacular API Key (kostenlos: https://spoonacular.com/food-api)
- Anthropic API Key (für Claude AI Features)

## Installation

### 1. Repository klonen

```bash
cd /opt/apps
git clone https://github.com/Pittisonfire/food-planer.git
cd food-planer
```

### 2. Environment Variablen setzen

```bash
cp backend/.env.example backend/.env
nano backend/.env
```

Füge deine API Keys ein:
```
DATABASE_URL=postgresql://foodplaner_user:foodplaner_password@db:5432/foodplaner
SPOONACULAR_API_KEY=dein_spoonacular_key
ANTHROPIC_API_KEY=dein_anthropic_key
DAILY_CALORIE_TARGET=1800
```

### 3. Container starten

```bash
docker compose up -d --build
```

### 4. App öffnen

- **Frontend**: http://SERVER_IP:8080
- **API Docs**: http://SERVER_IP:8001/docs

## Befehle

```bash
# Status prüfen
docker compose ps

# Logs anzeigen
docker compose logs backend --tail 50

# Neustarten
docker compose restart

# Komplett neu bauen
docker compose down
docker compose up -d --build

# Datenbank zurücksetzen
docker compose down -v
docker compose up -d --build
```

## API Endpoints

| Endpoint | Methode | Beschreibung |
|----------|---------|--------------|
| `/api/recipes/search` | POST | Rezepte suchen |
| `/api/recipes/instagram` | POST | Instagram Import |
| `/api/recipes` | GET | Gespeicherte Rezepte |
| `/api/pantry` | GET/POST/DELETE | Vorrat verwalten |
| `/api/mealplan` | GET/POST/DELETE | Wochenplan |
| `/api/shopping` | GET/POST/DELETE | Einkaufsliste |

## Spoonacular API Key holen

1. Gehe zu https://spoonacular.com/food-api
2. Klicke auf "Start Now" (kostenlos)
3. Registriere dich
4. Kopiere den API Key aus dem Dashboard

**Kostenlos:** 150 Requests/Tag

## Architektur

```
food-planer/
├── backend/           # FastAPI Backend
│   ├── app/
│   │   ├── api/       # API Endpoints
│   │   ├── core/      # Config, Database
│   │   ├── models/    # SQLAlchemy Models
│   │   └── services/  # Spoonacular, Claude
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/          # React SPA (als HTML)
│   └── index.html
├── nginx/             # Nginx Config
└── docker-compose.yml
```

## Lizenz

MIT - Pathics 2025
