"""
Tool: get_weather
Calls the free Open-Meteo API (no API key required):
1. Geocoding endpoint to turn a city name into lat/lon
2. Forecast endpoint to get current conditions
"""
import requests

TOOL_SCHEMA = {
    "name": "get_weather",
    "description": "Get the current weather conditions for a given city.",
    "input_schema": {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City name, e.g. 'Hyderabad' or 'Paris'"}
        },
        "required": ["city"],
    },
}

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog", 51: "light drizzle", 61: "light rain",
    63: "moderate rain", 65: "heavy rain", 71: "light snow", 80: "rain showers",
    95: "thunderstorm",
}


def run(city: str) -> dict:
    try:
        geo = requests.get(GEOCODE_URL, params={"name": city, "count": 1}, timeout=10).json()
    except requests.RequestException as e:
        return {"error": f"Network error contacting geocoding API: {e}"}

    results = geo.get("results")
    if not results:
        return {"error": f"Could not find a location matching '{city}'"}

    loc = results[0]
    lat, lon = loc["latitude"], loc["longitude"]

    try:
        wx = requests.get(
            FORECAST_URL,
            params={"latitude": lat, "longitude": lon, "current_weather": True},
            timeout=10,
        ).json()
    except requests.RequestException as e:
        return {"error": f"Network error contacting forecast API: {e}"}

    current = wx.get("current_weather", {})
    code = current.get("weathercode")

    return {
        "city": loc.get("name"),
        "country": loc.get("country"),
        "temperature_c": current.get("temperature"),
        "windspeed_kmh": current.get("windspeed"),
        "condition": WEATHER_CODES.get(code, f"code {code}"),
        "observed_at": current.get("time"),
    }
