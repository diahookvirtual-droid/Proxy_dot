import secrets
import time
from typing import Optional

from config import (
    CATEGORY_HELP,
    CATEGORY_LABEL,
    DEFAULT_DISTANCE_KM,
    DEFAULT_MINUTES,
    DRAFT_TTL_SECONDS,
    INTAKE_TTL_SECONDS,
    SERVICES,
    compute_pricing,
)
from nlp import LocationPin, ParsedRequest, classify
from storage import save_new_booking
from whatsapp_client import send_buttons, send_text

DRAFTS: dict[str, dict] = {}
PENDING_INTAKE: dict[str, dict] = {}

MENU = "\n".join(f"• {CATEGORY_HELP[c]}" for c in SERVICES)
WELCOME = (
    f"Namaste! 🙏 Main aapke ye kaam karwa sakta hoon:\n{MENU}\n\n"
    "Bas apni request likh bhejiye, jaise: _\"Kal subah 7 baje Civil Hospital ki OPD slip leni hai\"_"
)
LOCATION_HOW_TO = (
    "📲 *WhatsApp par Location Pin kaise bhejein:*\n"
    "1. Neeche message box ke paas *📎 (Clip)* ya *+* icon par tap karein\n"
    "2. *Location* select karein\n"
    "3. *Send your current location* par tap karein _(ya upar search karke exact jagah pin karein)_"
)


def format_when(p: ParsedRequest) -> str:
    return " ".join(x for x in (p.requested_date, p.requested_time or p.time_window) if x) or "Nahi bataya"


def format_location_label(pin: LocationPin) -> str:
    parts = [x for x in (pin.name, pin.address) if x]
    if parts:
        return f"{', '.join(parts)} ({pin.maps_url})"
    if pin.latitude is not None and pin.longitude is not None:
        return f"{pin.latitude:.5f}, {pin.longitude:.5f} ({pin.maps_url})"
    return pin.maps_url


def get_missing_mandatory_prompts(p: ParsedRequest) -> list[str]:
    if p.category in ("OPD_TOKEN", "NICHE_SOURCING", "SITE_INSPECTION") and not p.location_pin:
        purpose = {
            "OPD_TOKEN": "Patient pickup / OPD token delivery ki *Google Maps Location Pin*",
            "NICHE_SOURCING": "Delivery / coordination ke liye apni *Google Maps Location Pin*",
            "SITE_INSPECTION": "Inspect karne wale plot/property ki *Google Maps Location Pin*",
        }[p.category]
        return [f"{purpose}\n\n{LOCATION_HOW_TO}"]

    prompts: list[str] = []

    if p.category == "NICHE_SOURCING":
        if not p.item_details and not p.summary:
            prompts.append("Kaunsa *item / medicine / sweet* aur kitni quantity chahiye")

    elif p.category == "OPD_TOKEN":
        if not p.target_entity:
            prompts.append("*Hospital Name* (kis hospital jaana hai?)")
        if not p.patient_name:
            prompts.append("*Patient Name* (full name)")
        if not p.patient_age or not p.patient_phone:
            missing_ap = []
            if not p.patient_age:
                missing_ap.append("Age")
            if not p.patient_phone:
                missing_ap.append("10-digit Mobile Number")
            prompts.append(f"*{' & '.join(missing_ap)}* (e.g. `47, 9876543210` — mobile no. poora 10 digit ka hona chahiye)")
        if not p.requested_date or not (p.requested_time or p.time_window):
            prompts.append("*Date & Preferred Slot* (e.g. `kal subah 7 baje`)")
        if not p.department_or_doctor:
            prompts.append("*Department / Doctor* (e.g. `Gastric / Dr. Anand`)")
        if not p.visit_type and not p.uhid_or_card:
            prompts.append("*Visit Type / Hospital Card*: `New` ya `Follow-up`, aur UHID/card number (agar nahi hai toh `New` likhein)")

    return prompts


def format_intake_prompt(p: ParsedRequest, missing_prompts: list[str]) -> str:
    if p.category in ("OPD_TOKEN", "NICHE_SOURCING", "SITE_INSPECTION") and not p.location_pin:
        title = {
            "OPD_TOKEN": "📍 *Step 1: Patient ki WhatsApp Location Pin bhejein*\n_(Typed address ki zaroorat nahi — bina location pin ke booking aage nahi badhegi)_",
            "NICHE_SOURCING": "📍 *Step 1: Apni WhatsApp Location Pin bhejein*\n_(Typed address ki zaroorat nahi — bina location pin ke booking aage nahi badhegi)_",
            "SITE_INSPECTION": "📍 *Step 1: Site ki WhatsApp Location Pin bhejein*\n_(Bina site location pin ke booking aage nahi badhegi)_",
        }[p.category]
        return f"{title}\n\n• {missing_prompts[0]}"

    ask_lines = "\n".join(f"• {item}" for item in missing_prompts)
    if p.category == "OPD_TOKEN":
        collected = []
        if p.location_pin:
            collected.append("Location Pin ✅")
        if p.target_entity:
            collected.append(f"Hospital: {p.target_entity}")
        if p.patient_name:
            collected.append(f"Name: {p.patient_name}")
        if p.patient_age:
            collected.append(f"Age: {p.patient_age}")
        if p.patient_phone:
            collected.append(f"Phone: {p.patient_phone}")
        if p.department_or_doctor:
            collected.append(f"Dept/Dr: {p.department_or_doctor}")
        if p.requested_date or p.requested_time or p.time_window:
            collected.append(f"Slot: {format_when(p)}")
        if p.visit_type or p.uhid_or_card:
            collected.append(f"Visit/UHID: {' / '.join(x for x in (p.visit_type, p.uhid_or_card) if x)}")

        collected_banner = f"✅ *Abhi tak mili details:* {', '.join(collected)}\n\n" if collected else ""
        return (
            f"🏥 *OPD Token* booking ke liye hospital receptionist ko ye details chahiye:\n\n"
            f"{collected_banner}"
            f"{ask_lines}\n\n"
            f"💡 _Example ek hi message mein:_ `Civil Hospital, Ramesh Sharma, 72, 9876543210, kal subah, Gastric / Dr. Anand, New`"
        )

    header = {
        "NICHE_SOURCING": "🛒 *Niche Sourcing* aage badhane ke liye kripya item details bhejein:",
        "SITE_INSPECTION": "📍 *Site Inspection* aage badhane ke liye details bhejein:",
    }.get(p.category, "Aage badhne ke liye kripya ye details bhejein:")
    return f"{header}\n\n{ask_lines}"


async def send_quote_and_confirm(sender: str, p: ParsedRequest) -> None:
    mins = p.est_duration_minutes or DEFAULT_MINUTES[p.category]
    q = compute_pricing(p.category, mins, DEFAULT_DISTANCE_KM)
    ref = f"TSK-{secrets.token_hex(3).upper()}"
    DRAFTS[ref] = {"customer": sender, "parsed": p.model_dump(), "quote": q, "created": time.time()}

    place = (
        " / ".join(x for x in (p.target_entity, p.locality) if x)
        or (format_location_label(p.location_pin) if p.location_pin else None)
        or "Nahi bataya"
    )
    lines = [
        f"🧐 *Maine aapki request ye samjhi ({ref}):*",
        f"• Kaam: {p.summary}",
        f"• Type: {CATEGORY_LABEL[p.category]}",
        f"• Jagah: {place}",
        f"• Kab: {format_when(p)}",
    ]
    if p.location_pin:
        lines.append(f"• Google Maps Pin: {format_location_label(p.location_pin)}")

    if p.category == "OPD_TOKEN":
        lines.append(f"• Destination Hospital: {p.target_entity}")
        lines.append(
            "• Service: Runner patient ko hospital le jayega, "
            "OPD token lega aur visit ke dauran assistance dega."
        )
        patient_line = ", ".join(
            x
            for x in (
                f"Naam: {p.patient_name}" if p.patient_name else None,
                f"Umar: {p.patient_age}" if p.patient_age else None,
                f"Phone: {p.patient_phone}" if p.patient_phone else None,
                f"Dept/Dr: {p.department_or_doctor}" if p.department_or_doctor else None,
                f"Visit: {p.visit_type}" if p.visit_type else None,
                f"UHID/Card: {p.uhid_or_card}" if p.uhid_or_card else None,
            )
            if x
        )
        if patient_line:
            lines.append(f"• Patient/OPD: {patient_line}")
    elif p.category == "NICHE_SOURCING":
        if p.item_details:
            lines.append(f"• Item / List: {p.item_details}")
        lines.append("• Service: Runner shop se item lekar aapki pin location par pahunchayega.")

    lines.append(f"• Anumaanit samay: {mins} min")
    if p.missing_details:
        lines.append(f"⚠️ Ye detail missing hai: {', '.join(p.missing_details)}")
    lines += ["", f"💰 *Service fee: ₹{q['total']}*"]
    parts = [f"base ₹{q['base']}"]
    if q["time_charge"]:
        parts.append(f"time ₹{q['time_charge']}")
    if q["distance_charge"]:
        parts.append(f"distance ₹{q['distance_charge']}")
    if len(parts) > 1:
        lines.append(f"   ({' + '.join(parts)})")
    if p.needs_purchase:
        lines.append("• Item ka kharcha aap seedha shop ko UPI se denge (alag se).")
    lines += ["", "*Kya ye sahi hai?*"]

    await send_buttons(
        sender,
        "\n".join(lines),
        [
            {"id": f"CONFIRM_{ref}", "title": "Haan, sahi hai"},
            {"id": f"EDIT_{ref}", "title": "Nahi, badlein"},
        ],
    )


async def process_and_reply(sender: str, text: str) -> None:
    active_intake = PENDING_INTAKE.get(sender)
    existing_parsed: Optional[ParsedRequest] = None
    previous_missing: Optional[list[str]] = None
    if active_intake:
        if time.time() - active_intake["created"] <= INTAKE_TTL_SECONDS:
            existing_parsed = active_intake["parsed"]
            previous_missing = active_intake.get("missing")
        else:
            PENDING_INTAKE.pop(sender, None)

    p = await classify(text, existing=existing_parsed, missing_prompts=previous_missing)

    if p.category == "UNSUPPORTED":
        PENDING_INTAKE.pop(sender, None)
        return await send_text(
            sender,
            "⚠️ *Service Unavailable*\nKshama karein, ye request hamari policies ke bahar hai. "
            "Hum ghar ke andar ka kaam, rishwat/illegal expediting, ya sharab-tambaakoo jaisi cheezein support nahi karte.",
        )
    if p.category == "GENERAL_QUERY":
        PENDING_INTAKE.pop(sender, None)
        return await send_text(sender, WELCOME)
    if p.category == "UNCLEAR":
        return await send_text(
            sender,
            "Main aapki request poori tarah samajh nahi paya 🙏\n"
            "Kripya batayein: *kaunsa kaam, kahan, aur kab?*\n\n" + MENU,
        )

    missing_prompts = get_missing_mandatory_prompts(p)
    if missing_prompts:
        PENDING_INTAKE[sender] = {"parsed": p, "missing": missing_prompts, "created": time.time()}
        return await send_text(sender, format_intake_prompt(p, missing_prompts))

    PENDING_INTAKE.pop(sender, None)
    await send_quote_and_confirm(sender, p)


async def process_location_reply(sender: str, loc: dict) -> None:
    lat = loc.get("latitude")
    lng = loc.get("longitude")
    if lat is None or lng is None:
        return await send_text(sender, f"Location read nahi ho payi 🙏 Dobara bhejein:\n\n{LOCATION_HOW_TO}")

    maps_url = f"https://maps.google.com/?q={lat},{lng}"
    pin = LocationPin(
        latitude=float(lat),
        longitude=float(lng),
        name=(loc.get("name") or "").strip()[:100] or None,
        address=(loc.get("address") or "").strip()[:160] or None,
        maps_url=maps_url,
    )

    active_intake = PENDING_INTAKE.get(sender)
    if not active_intake or time.time() - active_intake["created"] > INTAKE_TTL_SECONDS:
        PENDING_INTAKE.pop(sender, None)
        return await send_text(
            sender,
            f"📍 Location mil gayi ({maps_url})! Ab kripya batayein aapko *kaunsa kaam* karwana hai?\n\n{MENU}",
        )

    p: ParsedRequest = active_intake["parsed"]
    p.location_pin = pin

    missing_prompts = get_missing_mandatory_prompts(p)
    if missing_prompts:
        PENDING_INTAKE[sender] = {"parsed": p, "missing": missing_prompts, "created": time.time()}
        return await send_text(sender, format_intake_prompt(p, missing_prompts))

    PENDING_INTAKE.pop(sender, None)
    await send_quote_and_confirm(sender, p)


async def handle_button(sender: str, button_id: str) -> None:
    action, _, ref = button_id.partition("_")
    draft = DRAFTS.get(ref)
    if not draft or draft["customer"] != sender or time.time() - draft["created"] > DRAFT_TTL_SECONDS:
        DRAFTS.pop(ref, None)
        return await send_text(sender, "Ye quote expire ho gaya hai. Kripya request dobara bhejein.")
    if action == "CONFIRM":
        DRAFTS.pop(ref, None)
        PENDING_INTAKE.pop(sender, None)
        await save_new_booking(ref, sender, draft["parsed"], draft["quote"])
        await send_text(
            sender,
            f"✅ *{ref} confirm ho gaya!* Service fee ₹{draft['quote']['total']}. "
            "Hum aapke paas ka verified helper dhoondh rahe hain, update jaldi milega.",
        )
    elif action == "EDIT":
        DRAFTS.pop(ref, None)
        PENDING_INTAKE.pop(sender, None)
        await send_text(
            sender,
            "Koi baat nahi 🙏 Kripya sahi details ke saath request dobara bhejein (kaunsa kaam, kahan, kab).",
        )