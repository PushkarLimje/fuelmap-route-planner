# models.py
from pydantic import BaseModel
from typing import Optional

# ── Request ───────────────────────────────────────────────────────────────────
class RoutePlanRequest(BaseModel):
    start: str
    destination: str
    vehicle_type: str = "petrol"       # "petrol" | "ev"

    # Petrol fields
    mileage: Optional[float] = 15.0    # km/L
    fuel: Optional[float] = 0.0        # litres available

    # EV fields
    battery_capacity: Optional[float] = 50.0   # kWh
    current_charge: Optional[float] = 0.0      # kWh available
    range_per_kwh: Optional[float] = 6.0       # km/kWh

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "start": "Pune",
                    "destination": "Mumbai",
                    "vehicle_type": "petrol",
                    "mileage": 15.0,
                    "fuel": 5.0
                },
                {
                    "start": "Bangalore",
                    "destination": "Mysore",
                    "vehicle_type": "ev",
                    "battery_capacity": 50.0,
                    "current_charge": 30.0,
                    "range_per_kwh": 6.0
                }
            ]
        }

# ── Sub-models ────────────────────────────────────────────────────────────────
class Station(BaseModel):
    name: str
    lat: float
    lon: float
    type: str  # "fuel" | "charging"

class Direction(BaseModel):
    instruction: str
    distance: str
    icon: str

class Coordinate(BaseModel):
    lat: float
    lng: float

class RouteOption(BaseModel):
    id: str
    type: str                          # "Direct Route" | "Via Fuel Station" | "Via Charging Station"
    distance_km: float
    duration_min: int
    duration_str: str                  # "1h 20m"
    energy_required: float             # litres or kWh
    energy_unit: str                   # "L" | "kWh"
    fuel_cost: float                   # ₹ estimate (0 for EV)
    waypoints: list[Coordinate]        # [start, (station?), dest]
    path_coordinates: list[Coordinate] # full road polyline from OSRM
    directions: list[dict]             # turn-by-turn
    station: Optional[Station] = None

# ── Response ──────────────────────────────────────────────────────────────────
class RoutePlanResponse(BaseModel):
    success: bool
    start: str
    destination: str
    start_coords: Coordinate
    dest_coords: Coordinate
    vehicle_type: str
    routes: list[RouteOption]          # sorted by distance
    needs_stop: bool                   # true if available energy < required