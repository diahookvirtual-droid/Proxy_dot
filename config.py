import os
from pathlib import Path
import pytz
from dotenv import load_dotenv

load_dotenv()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "my_secure_verify_token")
APP_SECRET = os.getenv("META_APP_SECRET")
GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "v21.0")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.4"))

TZ = pytz.timezone(os.getenv("SERVER_TIMEZONE", "Asia/Kolkata"))
DEFAULT_DISTANCE_KM = 3.5
DRAFT_TTL_SECONDS = 30 * 60
INTAKE_TTL_SECONDS = 30 * 60
BOOKINGS_FILE = Path(os.getenv("BOOKINGS_FILE", "bookings.json"))

SERVICES = ["CIVIC_QUEUE", "OPD_TOKEN", "DOCUMENT_RUN", "NICHE_SOURCING", "SITE_INSPECTION"]

CATEGORY_HELP = {
    "CIVIC_QUEUE": "Queue standing at Tehsil/RTO/govt offices/Tatkal ticket counters",
    "OPD_TOKEN": "Hospital OPD token/slip pickup, lab report runs",
    "DOCUMENT_RUN": "Collect/deliver/submit stamp paper, affidavits, files",
    "NICHE_SOURCING": "Buy & fetch specific items (sweets, wholesale medicines)",
    "SITE_INSPECTION": "Geo-tagged photo/video check of a plot or property",
}

CATEGORY_LABEL = {
    "CIVIC_QUEUE": "Sarkari office ki line",
    "OPD_TOKEN": "OPD token / lab report",
    "DOCUMENT_RUN": "Document run",
    "NICHE_SOURCING": "Khareed ke laana",
    "SITE_INSPECTION": "Site inspection (photo/video)",
}

RATES = {
    "CIVIC_QUEUE": (100.0, 80.0),
    "OPD_TOKEN": (120.0, 60.0),
    "DOCUMENT_RUN": (80.0, 0.0),
    "NICHE_SOURCING": (50.0, 0.0),
    "SITE_INSPECTION": (150.0, 0.0),
}

DEFAULT_MINUTES = {
    "CIVIC_QUEUE": 120,
    "OPD_TOKEN": 90,
    "DOCUMENT_RUN": 30,
    "NICHE_SOURCING": 45,
    "SITE_INSPECTION": 40,
}


def compute_pricing(category: str, duration_mins: int, distance_km: float) -> dict:
    base, per_hour = RATES[category]
    time_charge = duration_mins / 60 * per_hour
    dist_charge = max(0.0, distance_km - 2.0) * 10.0
    total = round(base + time_charge + dist_charge)
    runner = round(total * 0.75)
    return {
        "base": round(base),
        "time_charge": round(time_charge),
        "distance_charge": round(dist_charge),
        "total": total,
        "runner_payout": runner,
        "platform_margin": total - runner,
    }


def log_startup_config() -> None:
    print(
        f"[config] WHATSAPP_TOKEN={'ok' if WHATSAPP_TOKEN else 'MISSING'} "
        f"PHONE_NUMBER_ID={PHONE_NUMBER_ID or 'MISSING'} "
        f"GROQ_API_KEY={'ok' if GROQ_API_KEY else 'MISSING (local rules only)'} "
        f"BOOKINGS_FILE={BOOKINGS_FILE}"
    )