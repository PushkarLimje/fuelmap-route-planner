# FuelMap Route Planner — FastAPI Microservice

Handles all route calculation so the Flutter app makes just ONE API call.

## What it does
- Geocodes start + destination (Nominatim) — **in parallel**
- Calculates distance/duration (TomTom) — **in parallel with OSRM**
- Fetches road polyline (OSRM) — **in parallel with TomTom**  
- Finds fuel/charging stations if needed — **then runs station routes in parallel**
- Returns everything in one response

## Run locally

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Test: http://localhost:8000/docs  (auto-generated Swagger UI)

## Flutter — local testing

In `plan_route_page.dart`, change:
```dart
const _fastApiBase = 'http://10.0.2.2:8000';  // Android emulator → localhost
// const _fastApiBase = 'http://localhost:8000'; // for web
```

## Deploy to Render (free)

1. Push this folder to a GitHub repo
2. Go to https://render.com → New Web Service
3. Connect repo, set:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Add env var: `TOMTOM_KEY = your_key_here`
5. Copy the deployed URL (e.g. `https://fuelmap-route-planner.onrender.com`)
6. Update `_fastApiBase` in Flutter to that URL

## API

### POST /routes/plan

**Request:**
```json
{
  "start": "Pune",
  "destination": "Mumbai",
  "vehicle_type": "petrol",
  "mileage": 15.0,
  "fuel": 5.0
}
```

**EV Request:**
```json
{
  "start": "Bangalore",
  "destination": "Mysore",
  "vehicle_type": "ev",
  "battery_capacity": 50.0,
  "current_charge": 30.0,
  "range_per_kwh": 6.0
}
```

**Response:**
```json
{
  "success": true,
  "start": "Pune",
  "destination": "Mumbai",
  "start_coords": {"lat": 18.52, "lng": 73.85},
  "dest_coords": {"lat": 19.07, "lng": 72.87},
  "vehicle_type": "petrol",
  "needs_stop": true,
  "routes": [
    {
      "id": "direct",
      "type": "Direct Route",
      "distance_km": 148.5,
      "duration_min": 182,
      "duration_str": "3h 2m",
      "energy_required": 9.9,
      "energy_unit": "L",
      "fuel_cost": 1029.6,
      "waypoints": [...],
      "path_coordinates": [...],  // full OSRM road polyline
      "directions": [...],         // turn-by-turn from TomTom
      "station": null
    },
    {
      "id": "via-HP_Petrol_Pump",
      "type": "Via Fuel Station",
      "station": {
        "name": "HP Petrol Pump",
        "lat": 18.9,
        "lng": 73.1,
        "type": "fuel"
      },
      ...
    }
  ]
}
```

### GET /reverse-geocode?lat=18.52&lon=73.85
Returns human-readable address for coordinates.

### GET /health
Returns service status.