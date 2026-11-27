import asyncio
import datetime
import json
from typing import Optional

from config import BOOKINGS_FILE, TZ

_bookings_lock = asyncio.Lock()


def _read_bookings_sync() -> list[dict]:
    if not BOOKINGS_FILE.exists():
        return []
    try:
        data = json.loads(BOOKINGS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as ex:
        print(f"[bookings] failed to read {BOOKINGS_FILE}: {ex}")
        return []


def _write_bookings_sync(records: list[dict]) -> None:
    BOOKINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = BOOKINGS_FILE.with_suffix(BOOKINGS_FILE.suffix + ".tmp")
    tmp_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(BOOKINGS_FILE)


async def save_new_booking(ref: str, customer: str, parsed: dict, quote: dict) -> dict:
    record = {
        "ref": ref,
        "customer_whatsapp": customer,
        "status": "PENDING_RUNNER",
        "runner_name": None,
        "accepted_at": None,
        "created_at": datetime.datetime.now(TZ).isoformat(),
        "parsed_request": parsed,
        "quote": quote,
    }
    async with _bookings_lock:
        records = _read_bookings_sync()
        records = [r for r in records if r.get("ref") != ref]
        records.append(record)
        _write_bookings_sync(records)
    return record


async def accept_booking_by_runner(ref: str, runner_name: str) -> Optional[dict]:
    async with _bookings_lock:
        records = _read_bookings_sync()
        for rec in records:
            if rec.get("ref") == ref:
                rec["runner_name"] = runner_name.strip()
                rec["status"] = "RUNNER_ACCEPTED"
                rec["accepted_at"] = datetime.datetime.now(TZ).isoformat()
                _write_bookings_sync(records)
                return rec
    return None