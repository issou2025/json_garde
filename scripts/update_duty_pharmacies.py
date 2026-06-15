#!/usr/bin/env python3
"""Met a jour la liste publique des pharmacies de garde de Niamey."""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SOURCE_URL = "https://2424pharmaniger.com/pharmacies-garde"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "pharmacies_garde_current.json"
ANNOUNCEMENT_PATH = Path(__file__).resolve().parents[1] / "announcement.txt"
CITY = "Niamey"
MIN_PHARMACIES = 5
NIAMEY_TIMEZONE = timezone(timedelta(hours=1))
STALE_ALERT_HOUR = 6


class SourceUnavailableError(RuntimeError):
    """The remote source cannot safely produce a new publication."""


def niamey_now() -> datetime:
    return datetime.now(NIAMEY_TIMEZONE)


def clean(value: str) -> str:
    return " ".join(value.split()).strip()


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "_", ascii_value).strip("_")


def format_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) == 8:
        return " ".join(digits[index : index + 2] for index in range(0, 8, 2))
    return ""


def load_announcement() -> str:
    try:
        return clean(ANNOUNCEMENT_PATH.read_text(encoding="utf-8"))
    except OSError:
        return ""


def compose_warning(source_date) -> str:
    return " ".join(
        part
        for part in (
            load_announcement(),
            f"Liste publiée pour le {source_date.strftime('%d/%m/%Y')}.",
            "Appelez toujours la pharmacie avant de vous déplacer.",
        )
        if part
    )


class GuardPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.in_title = False
        self.card: dict | None = None
        self.card_depth = 0
        self.capture_field: str | None = None
        self.capture_tag: str | None = None
        self.capture_parts: list[str] = []
        self.cards: list[dict] = []

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {key: value or "" for key, value in attrs_list}
        classes = set(attrs.get("class", "").split())

        if tag == "title":
            self.in_title = True

        if tag == "div" and "pharmacy-card" in classes and self.card is None:
            self.card = {
                "name": "",
                "city": "",
                "address": "",
                "phone": "",
                "latitude": None,
                "longitude": None,
                "suspended": "pharmacy-suspended" in classes,
            }
            self.card_depth = 1
            return

        if self.card is None:
            return

        if tag == "div":
            self.card_depth += 1

        if tag == "h3":
            self._start_capture("name", tag)
        elif tag == "span" and "line-clamp-2" in classes:
            self._start_capture("address", tag)
        elif tag == "span" and "truncate" in classes and not self.card["city"]:
            self._start_capture("city", tag)
        elif tag == "a" and attrs.get("href", "").startswith("tel:"):
            self.card["phone"] = attrs["href"][4:]
        elif tag == "a" and "google.com/maps/dir" in attrs.get("href", ""):
            match = re.search(r"destination=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", attrs["href"])
            if match:
                self.card["latitude"] = float(match.group(1))
                self.card["longitude"] = float(match.group(2))

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False

        if self.card is None:
            return

        if self.capture_tag == tag and self.capture_field:
            self.card[self.capture_field] = clean("".join(self.capture_parts))
            self.capture_field = None
            self.capture_tag = None
            self.capture_parts = []

        if tag == "div":
            self.card_depth -= 1
            if self.card_depth == 0:
                self.cards.append(self.card)
                self.card = None

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        if self.capture_field:
            self.capture_parts.append(data)

    def _start_capture(self, field: str, tag: str) -> None:
        self.capture_field = field
        self.capture_tag = tag
        self.capture_parts = []

    @property
    def title(self) -> str:
        return clean("".join(self.title_parts))


def download_source() -> str:
    request = Request(
        SOURCE_URL,
        headers={
            "User-Agent": "json-garde-updater/1.0 (+https://github.com/issou2025/json_garde)",
            "Accept-Language": "fr-FR,fr;q=0.9",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise SourceUnavailableError(
                    f"La source a repondu avec le statut {response.status}"
                )
            return response.read().decode("utf-8", errors="replace")
    except SourceUnavailableError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise SourceUnavailableError(f"Source indisponible: {error}") from error


def build_payload(html: str) -> dict:
    parser = GuardPageParser()
    parser.feed(html)

    date_match = re.search(r"(\d{2}/\d{2}/\d{4})", parser.title)
    if not date_match:
        raise SourceUnavailableError("Date absente du titre de la source")
    source_date = datetime.strptime(date_match.group(1), "%d/%m/%Y").date()
    today = niamey_now().date()
    if source_date != today:
        raise SourceUnavailableError(
            f"Liste source datee du {source_date}, aujourd'hui est le {today}"
        )

    pharmacies = []
    seen_ids: set[str] = set()
    for card in parser.cards:
        if clean(card["city"]).casefold() != CITY.casefold():
            continue
        name = clean(card["name"])
        address = clean(card["address"])
        phone = format_phone(card["phone"])
        if not name or not address or not phone:
            continue
        pharmacy_id = slugify(name)
        if pharmacy_id in seen_ids:
            continue
        seen_ids.add(pharmacy_id)
        has_gps = card["latitude"] is not None and card["longitude"] is not None
        pharmacies.append(
            {
                "id": pharmacy_id,
                "name": name,
                "district": clean(address.split(",", 1)[0]),
                "commune": CITY,
                "address": address,
                "landmark": address,
                "phone_numbers": [phone],
                "latitude": card["latitude"],
                "longitude": card["longitude"],
                "gps_status": "confirmed" if has_gps else "unverified",
                "is_open": not card["suspended"],
                "note": "De garde 24h/24 - Appelez avant déplacement",
            }
        )

    if len(pharmacies) < MIN_PHARMACIES:
        raise SourceUnavailableError(
            f"Seulement {len(pharmacies)} pharmacies valides trouvees; publication annulee"
        )

    pharmacies.sort(key=lambda item: item["name"].casefold())
    now = niamey_now()
    iso_date = source_date.isoformat()
    return {
        "status": "success",
        "city": CITY,
        "country": "Niger",
        "date": iso_date,
        "week_start": iso_date,
        "week_end": iso_date,
        "updated_at": now.isoformat(timespec="seconds"),
        "source_name": "2424PharmaNiger - Pharmacies de garde aujourd'hui",
        "source_url": SOURCE_URL,
        "warning": compose_warning(source_date),
        "data": pharmacies,
    }


def unchanged(existing: dict, new_payload: dict) -> bool:
    keys = ("status", "city", "country", "date", "week_start", "week_end", "source_name", "source_url", "warning", "data")
    return all(existing.get(key) == new_payload.get(key) for key in keys)


def can_keep_existing_publication() -> bool:
    try:
        existing = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    is_valid = (
        existing.get("status") == "success"
        and existing.get("city") == CITY
        and isinstance(existing.get("data"), list)
        and len(existing["data"]) >= MIN_PHARMACIES
    )
    if not is_valid:
        return False
    try:
        publication_date = datetime.strptime(existing["date"], "%Y-%m-%d").date()
    except (KeyError, TypeError, ValueError):
        return False
    now = niamey_now()
    return publication_date == now.date() or now.hour < STALE_ALERT_HOUR


def update_existing_announcement() -> bool:
    try:
        existing = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        publication_date = datetime.strptime(existing["date"], "%Y-%m-%d").date()
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return False
    warning = compose_warning(publication_date)
    if existing.get("warning") == warning:
        return False
    existing["warning"] = warning
    OUTPUT_PATH.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return True


def main() -> int:
    try:
        payload = build_payload(download_source())
    except SourceUnavailableError as error:
        if not can_keep_existing_publication():
            raise
        announcement_updated = update_existing_announcement()
        print(
            f"AVERTISSEMENT: {error}. "
            "La derniere publication valide est conservee."
            + (
                " Le message public a ete mis a jour."
                if announcement_updated
                else ""
            ),
            file=sys.stderr,
        )
        return 0

    if OUTPUT_PATH.exists():
        try:
            existing = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
            if unchanged(existing, payload):
                print(f"Aucun changement: {len(payload['data'])} pharmacies deja publiees.")
                return 0
        except (OSError, json.JSONDecodeError):
            pass

    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Publication preparee: {len(payload['data'])} pharmacies pour {payload['date']}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERREUR: {error}", file=sys.stderr)
        raise SystemExit(1)
