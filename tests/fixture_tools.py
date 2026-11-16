"""Independently authored fixtures. Never present these as verified Places/Routes data."""
import unicodedata

PLACES = {
    "park": {"id": "park", "name": "Park Güell", "lat": 41.4145, "lng": 2.1527},
    "casa": {"id": "casa", "name": "Casa Batlló", "lat": 41.3917, "lng": 2.1649},
    "sol_old": {"id": "sol_old", "name": "Sol · Old Town (fictional)", "lat": 41.3835, "lng": 2.1742},
    "sol_eixample": {"id": "sol_eixample", "name": "Sol · Eixample (fictional)", "lat": 41.3955, "lng": 2.1621},
    "cathedral": {"id": "cathedral", "name": "Barcelona Cathedral", "lat": 41.3840, "lng": 2.1762},
}
ALIASES = {
    "park guell": ["park"], "casa batllo": ["casa"],
    "lunch at sol": ["sol_old", "sol_eixample"], "sol": ["sol_old", "sol_eixample"],
    "barcelona cathedral": ["cathedral"],
}
ROUTES = {("park", "casa"): 45, ("casa", "sol_old"): 25,
          ("casa", "sol_eixample"): 15, ("sol_old", "cathedral"): 8,
          ("sol_eixample", "cathedral"): 35}


def normalize(value: str) -> str:
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", value.lower())
                            if not unicodedata.combining(c)).split())


def lookup_place(name: str, city: str) -> dict:
    ids = ALIASES.get(normalize(name), []) if normalize(city) == "barcelona" else []
    candidates = [dict(PLACES[place_id]) for place_id in ids]
    return {"status": "resolved" if len(candidates) == 1 else "ambiguous" if candidates else "unresolved",
            "place": candidates[0] if len(candidates) == 1 else None,
            "candidates": candidates, "source": "Synthetic test fixture"}


def route_minutes(origin: str, destination: str) -> int | None:
    if origin == destination:
        return 0
    return ROUTES.get((origin, destination))
