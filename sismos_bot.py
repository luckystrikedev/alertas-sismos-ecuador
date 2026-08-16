"""
Bot de alertas sismicas para Ecuador via Telegram.

Consulta la API publica de USGS (sin API key) filtrada a la caja
geografica de Ecuador, y envia un mensaje de Telegram por cada sismo
nuevo (magnitud 4.0+) que no se haya notificado antes.

Requiere dos variables de entorno:
  TELEGRAM_BOT_TOKEN  -> token que te dio BotFather
  TELEGRAM_CHAT_ID    -> tu chat id (a donde llegan las alertas)
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# Caja geografica que cubre todo el territorio continental de Ecuador
MIN_LATITUDE = -5.5
MAX_LATITUDE = 1.6
MIN_LONGITUDE = -81.5
MAX_LONGITUDE = -75.0

MIN_MAGNITUDE = 4.0

# Cuantas horas hacia atras revisar en cada corrida
LOOKBACK_HOURS = 6

USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"

SENT_IDS_FILE = Path(__file__).parent / "sent_ids.json"


def load_sent_ids() -> set:
    if SENT_IDS_FILE.exists():
        with open(SENT_IDS_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_sent_ids(ids: set) -> None:
    # Solo guardamos los ultimos 500 para que el archivo no crezca sin limite
    trimmed = list(ids)[-500:]
    with open(SENT_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f)


def fetch_earthquakes() -> list:
    start_time = (datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    params = {
        "format": "geojson",
        "starttime": start_time,
        "minmagnitude": MIN_MAGNITUDE,
        "minlatitude": MIN_LATITUDE,
        "maxlatitude": MAX_LATITUDE,
        "minlongitude": MIN_LONGITUDE,
        "maxlongitude": MAX_LONGITUDE,
        "orderby": "time",
    }
    response = requests.get(USGS_URL, params=params, timeout=30)
    response.raise_for_status()
    return response.json().get("features", [])


def format_message(feature: dict) -> str:
    props = feature["properties"]
    coords = feature["geometry"]["coordinates"]  # [lon, lat, depth_km]
    lon, lat, depth = coords[0], coords[1], coords[2]

    event_time_utc = datetime.fromtimestamp(props["time"] / 1000, tz=timezone.utc)
    event_time_ec = event_time_utc - timedelta(hours=5)  # Ecuador es UTC-5

    magnitude = props.get("mag", "N/D")
    place = props.get("place", "Ubicacion desconocida")
    usgs_link = props.get("url", "")

    return (
        f"🚨 *Sismo detectado*\n\n"
        f"*Magnitud:* {magnitude}\n"
        f"*Lugar:* {place}\n"
        f"*Profundidad:* {depth:.1f} km\n"
        f"*Hora local (Ecuador):* {event_time_ec.strftime('%Y-%m-%d %H:%M')}\n\n"
        f"[Ver detalle en USGS]({usgs_link})"
    )


def send_telegram_message(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    response = requests.post(url, json=payload, timeout=30)
    if not response.ok:
        print(f"Error enviando mensaje a Telegram: {response.text}", file=sys.stderr)
        response.raise_for_status()


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en el entorno.", file=sys.stderr)
        sys.exit(1)

    sent_ids = load_sent_ids()
    earthquakes = fetch_earthquakes()

    new_count = 0
    for feature in earthquakes:
        event_id = feature["id"]
        if event_id in sent_ids:
            continue

        message = format_message(feature)
        send_telegram_message(token, chat_id, message)
        sent_ids.add(event_id)
        new_count += 1

    if new_count:
        save_sent_ids(sent_ids)
        print(f"Se enviaron {new_count} alerta(s) nueva(s).")
    else:
        print("No hay sismos nuevos que reportar.")


if __name__ == "__main__":
    main()
