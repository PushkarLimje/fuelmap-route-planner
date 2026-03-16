"""
FuelMap Route Planning Microservice
FastAPI backend that handles all route calculation logic:
  - Geocoding (Nominatim)
  - Route distance/duration (TomTom)
  - Road polyline (OSRM)
  - Nearby fuel/charging stations (Nominatim + TomTom)
  - Energy calculation
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import httpx
import math
from models import RoutePlanRequest, RoutePlanResponse, RouteOption, Station
from config import settings

app = FastAPI(
    title="FuelMap Route Planner",
    description="Microservice for fuel-efficient route planning",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Haversine distance ────────────────────────────────────────────────────────
def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# ── Nominatim geocode ─────────────────────────────────────────────────────────
async def geocode(client: httpx.AsyncClient, place: str) -> tuple[float, float] | None:
    try:
        r = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={"format": "json", "q": place, "limit": 1},
            headers={"User-Agent": "FuelMapFastAPI/1.0"},
            timeout=10.0
        )
        data = r.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        print(f"Geocode error for '{place}': {e}")
    return None

# ── TomTom reverse geocode ────────────────────────────────────────────────────
async def reverse_geocode(client: httpx.AsyncClient, lat: float, lon: float) -> str:
    try:
        r = await client.get(
            f"https://api.tomtom.com/search/2/reverseGeocode/{lat},{lon}.json",
            params={"key": settings.tomtom_key},
            timeout=8.0
        )
        data = r.json()
        addr = data.get("addresses", [{}])[0].get("address", {}).get("freeformAddress")
        return addr or f"{lat:.6f}, {lon:.6f}"
    except:
        return f"{lat:.6f}, {lon:.6f}"

# ── TomTom calculate route ────────────────────────────────────────────────────
async def tomtom_route(
    client: httpx.AsyncClient,
    waypoints: list[tuple[float, float]]
) -> dict | None:
    try:
        wp_str = ":".join(f"{lat},{lon}" for lat, lon in waypoints)
        r = await client.get(
            f"https://api.tomtom.com/routing/1/calculateRoute/{wp_str}/json",
            params={
                "traffic": "true",
                "instructionsType": "text",
                "key": settings.tomtom_key
            },
            timeout=15.0
        )
        data = r.json()
        if not data.get("routes"):
            return None

        route = data["routes"][0]
        summary = route["summary"]
        dist_km = summary["lengthInMeters"] / 1000
        dur_min = round(summary["travelTimeInSeconds"] / 60)

        # Extract turn-by-turn directions
        instructions = route.get("guidance", {}).get("instructions", [])
        directions = []
        for inst in instructions:
            maneuver = inst.get("maneuver", "")
            directions.append({
                "instruction": inst.get("message") or maneuver or "Continue",
                "distance": f"{round(inst['routeOffsetInMeters'])} m"
                    if "routeOffsetInMeters" in inst
                    else f"{round(inst.get('travelDistance', 0) / 1000, 1)} km",
                "icon": _direction_icon(maneuver)
            })

        return {"dist_km": dist_km, "dur_min": dur_min, "directions": directions}
    except Exception as e:
        print(f"TomTom route error: {e}")
        return None

def _direction_icon(maneuver: str) -> str:
    icons = {
        "TURN_LEFT": "↰", "TURN_RIGHT": "↱",
        "KEEP_LEFT": "↰", "KEEP_RIGHT": "↱",
        "BEAR_LEFT": "↰", "BEAR_RIGHT": "↱",
        "STRAIGHT": "↑", "ENTER_FREEWAY": "↑",
        "EXIT_FREEWAY": "↓", "ENTER_HIGHWAY": "↑",
        "CONTINUE": "↑", "ROUNDABOUT_LEFT": "⟲",
        "ROUNDABOUT_RIGHT": "⟳", "UTURN": "↶"
    }
    return icons.get(maneuver, "↑")

# ── OSRM polyline ─────────────────────────────────────────────────────────────
async def osrm_polyline(
    client: httpx.AsyncClient,
    waypoints: list[tuple[float, float]]
) -> list[dict]:
    try:
        wp_str = ";".join(f"{lon},{lat}" for lat, lon in waypoints)
        r = await client.get(
            f"https://router.project-osrm.org/route/v1/driving/{wp_str}",
            params={"overview": "full", "geometries": "geojson"},
            headers={"User-Agent": "FuelMapFastAPI/1.0"},
            timeout=10.0
        )
        data = r.json()
        if data.get("code") == "Ok":
            coords = data["routes"][0]["geometry"]["coordinates"]
            return [{"lat": c[1], "lng": c[0]} for c in coords]
    except Exception as e:
        print(f"OSRM error: {e}")
    # Fallback: straight line between waypoints
    return [{"lat": lat, "lng": lon} for lat, lon in waypoints]

# ── Find fuel stations (Nominatim) ────────────────────────────────────────────
async def find_fuel_stations(
    client: httpx.AsyncClient,
    src: tuple, dst: tuple
) -> list[dict]:
    try:
        mid_lat = (src[0] + dst[0]) / 2
        mid_lon = (src[1] + dst[1]) / 2
        r = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "format": "json",
                "q": f"fuel station near {mid_lat},{mid_lon}",
                "limit": 5
            },
            headers={"User-Agent": "FuelMapFastAPI/1.0"},
            timeout=8.0
        )
        stations = r.json()
        route_dist = haversine(*src, *dst)
        result = []
        for s in stations:
            slat, slon = float(s["lat"]), float(s["lon"])
            total = haversine(*src, slat, slon) + haversine(slat, slon, *dst)
            if total <= route_dist * 1.2:
                result.append({
                    "name": s["display_name"].split(",")[0],
                    "lat": slat, "lon": slon,
                    "type": "fuel"
                })
        return result[:3]
    except Exception as e:
        print(f"Fuel stations error: {e}")
        return []

# ── Find EV charging stations (TomTom → Nominatim fallback) ──────────────────
async def find_charging_stations(
    client: httpx.AsyncClient,
    src: tuple, dst: tuple
) -> list[dict]:
    try:
        mid_lat = (src[0] + dst[0]) / 2
        mid_lon = (src[1] + dst[1]) / 2
        route_dist = haversine(*src, *dst)
        radius = min(int(route_dist * 0.6 * 1000), 50000)

        r = await client.get(
            "https://api.tomtom.com/search/2/categorySearch/electric%20vehicle%20station.json",
            params={
                "lat": mid_lat, "lon": mid_lon,
                "radius": radius, "limit": 10,
                "key": settings.tomtom_key
            },
            timeout=10.0
        )
        data = r.json()
        results = data.get("results", [])

        if not results:
            return await _charging_fallback(client, src, dst)

        stations = []
        for res in results:
            slat = res["position"]["lat"]
            slon = res["position"]["lon"]
            total = haversine(*src, slat, slon) + haversine(slat, slon, *dst)
            if total <= route_dist * 1.3:
                stations.append({
                    "name": res.get("poi", {}).get("name", "EV Charging Station"),
                    "lat": slat, "lon": slon,
                    "type": "charging"
                })
        return stations[:3]
    except:
        return await _charging_fallback(client, src, dst)

async def _charging_fallback(client, src, dst):
    try:
        mid_lat = (src[0] + dst[0]) / 2
        mid_lon = (src[1] + dst[1]) / 2
        r = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "format": "json",
                "q": f"EV charging station near {mid_lat},{mid_lon}",
                "limit": 5
            },
            headers={"User-Agent": "FuelMapFastAPI/1.0"},
            timeout=8.0
        )
        data = r.json()
        return [{
            "name": s["display_name"].split(",")[0],
            "lat": float(s["lat"]), "lon": float(s["lon"]),
            "type": "charging"
        } for s in data[:3]]
    except:
        return []

# ── Build one route option ────────────────────────────────────────────────────
async def build_route_option(
    client: httpx.AsyncClient,
    route_id: str,
    route_type: str,
    waypoints: list[tuple],
    vehicle_type: str,
    mileage: float,
    range_per_kwh: float,
    station: dict | None = None
) -> RouteOption | None:
    # Run TomTom + OSRM concurrently
    tt_result, polyline = await asyncio.gather(
        tomtom_route(client, waypoints),
        osrm_polyline(client, waypoints)
    )
    if not tt_result:
        return None

    dist_km = tt_result["dist_km"]
    dur_min = tt_result["dur_min"]

    if vehicle_type == "petrol":
        energy = dist_km / mileage if mileage else 0
        unit = "L"
        fuel_cost = round(energy * settings.fuel_price_per_liter, 2)
    else:
        energy = dist_km / range_per_kwh if range_per_kwh else 0
        unit = "kWh"
        fuel_cost = 0.0

    h, m = divmod(dur_min, 60)
    duration_str = f"{h}h {m}m" if h > 0 else f"{m} mins"

    return RouteOption(
        id=route_id,
        type=route_type,
        distance_km=round(dist_km, 2),
        duration_min=dur_min,
        duration_str=duration_str,
        energy_required=round(energy, 2),
        energy_unit=unit,
        fuel_cost=fuel_cost,
        waypoints=[{"lat": lat, "lng": lon} for lat, lon in waypoints],
        path_coordinates=polyline,
        directions=tt_result["directions"],
        station=Station(**station) if station else None
    )

# ── Main endpoint ─────────────────────────────────────────────────────────────
@app.post("/routes/plan", response_model=RoutePlanResponse)
async def plan_route(req: RoutePlanRequest):
    async with httpx.AsyncClient() as client:
        # 1. Geocode start and destination in parallel
        src_coords, dst_coords = await asyncio.gather(
            geocode(client, req.start),
            geocode(client, req.destination)
        )

        if not src_coords:
            raise HTTPException(400, f"Could not geocode start: '{req.start}'")
        if not dst_coords:
            raise HTTPException(400, f"Could not geocode destination: '{req.destination}'")

        mileage = req.mileage or 15.0
        range_per_kwh = req.range_per_kwh or 6.0
        available_energy = req.fuel if req.vehicle_type == "petrol" else req.current_charge

        # 2. Build direct route
        direct = await build_route_option(
            client, "direct", "Direct Route",
            [src_coords, dst_coords],
            req.vehicle_type, mileage, range_per_kwh
        )
        if not direct:
            raise HTTPException(500, "Could not calculate route. Please try again.")

        options = [direct]

        # 3. Check if stop is needed
        needs_stop = (available_energy or 0) < direct.energy_required

        if needs_stop:
            # Find stations
            if req.vehicle_type == "petrol":
                stations = await find_fuel_stations(client, src_coords, dst_coords)
            else:
                stations = await find_charging_stations(client, src_coords, dst_coords)

            # Build via-station routes concurrently (max 2)
            station_tasks = [
                build_route_option(
                    client,
                    f"via-{s['name'].replace(' ', '_')}",
                    "Via Fuel Station" if req.vehicle_type == "petrol" else "Via Charging Station",
                    [src_coords, (s["lat"], s["lon"]), dst_coords],
                    req.vehicle_type, mileage, range_per_kwh,
                    station={
                        "name": s["name"],
                        "lat": s["lat"],
                        "lon": s["lon"],
                        "type": s["type"]
                    }
                )
                for s in stations[:2]
            ]
            station_results = await asyncio.gather(*station_tasks)
            options.extend([r for r in station_results if r is not None])

        # 4. Sort by distance
        options.sort(key=lambda r: r.distance_km)

        return RoutePlanResponse(
            success=True,
            start=req.start,
            destination=req.destination,
            start_coords={"lat": src_coords[0], "lng": src_coords[1]},
            dest_coords={"lat": dst_coords[0], "lng": dst_coords[1]},
            vehicle_type=req.vehicle_type,
            routes=options,
            needs_stop=needs_stop
        )

@app.get("/health")
async def health():
    return {"status": "ok", "service": "FuelMap Route Planner"}

@app.get("/reverse-geocode")
async def get_reverse_geocode(lat: float, lon: float):
    async with httpx.AsyncClient() as client:
        address = await reverse_geocode(client, lat, lon)
        return {"address": address}