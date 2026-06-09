"""Reusable CardDAV/local contacts service.

Routes, tools, and feature modules should use this service instead of
importing route-private helpers. The backing store stays the existing
CardDAV configuration with a local JSON fallback.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from src.constants import (
    CONTACTS_FILE as _CONTACTS_FILE,
    DATA_DIR as _DATA_DIR,
    SETTINGS_FILE as _SETTINGS_FILE,
)
from src.url_safety import check_outbound_url


logger = logging.getLogger(__name__)

DATA_DIR = Path(_DATA_DIR)
SETTINGS_FILE = Path(_SETTINGS_FILE)
LOCAL_CONTACTS_FILE = Path(_CONTACTS_FILE)

_contact_cache: Dict[str, object] = {"contacts": [], "fetched_at": None}


def load_settings() -> Dict:
    if SETTINGS_FILE.exists():
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    return {}


def save_settings(settings: Dict) -> None:
    from core.atomic_io import atomic_write_json

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(str(SETTINGS_FILE), settings, indent=2)


def get_carddav_config() -> Dict[str, str]:
    settings = load_settings()
    return {
        "url": settings.get("carddav_url", os.environ.get("CARDDAV_URL", "")),
        "username": settings.get("carddav_username", os.environ.get("CARDDAV_USERNAME", "")),
        "password": settings.get("carddav_password", os.environ.get("CARDDAV_PASSWORD", "")),
    }


def masked_carddav_config() -> Dict[str, str]:
    cfg = get_carddav_config()
    if cfg.get("password"):
        cfg["password"] = "***"
    return cfg


def update_carddav_config(data: Dict) -> Dict[str, bool]:
    settings = load_settings()
    for key in ("carddav_url", "carddav_username", "carddav_password"):
        if key in data:
            if key == "carddav_url" and str(data[key] or "").strip():
                settings[key] = validate_carddav_url(data[key])
            else:
                settings[key] = data[key]
    save_settings(settings)
    invalidate_cache()
    return {"success": True}


def carddav_configured(cfg: Optional[Dict] = None) -> bool:
    cfg = cfg or get_carddav_config()
    return bool((cfg.get("url") or "").strip())


def validate_carddav_url(url: str) -> str:
    cleaned = (url if isinstance(url, str) else "").strip().rstrip("/")
    ok, reason = check_outbound_url(
        cleaned,
        block_private=os.getenv("CARDDAV_BLOCK_PRIVATE_IPS", "false").lower() == "true",
    )
    if not ok:
        raise ValueError(f"Rejected CardDAV URL: {reason}")
    return cleaned


def carddav_base_url(cfg: Dict) -> str:
    return validate_carddav_url(cfg.get("url") or "")


def invalidate_cache() -> None:
    _contact_cache["fetched_at"] = None


def normalize_contact(contact: Dict) -> Dict:
    emails = []
    for email in contact.get("emails") or ([] if not contact.get("email") else [contact.get("email")]):
        email = str(email or "").strip()
        if email and email not in emails:
            emails.append(email)
    phones = []
    for phone in contact.get("phones") or ([] if not contact.get("phone") else [contact.get("phone")]):
        phone = str(phone or "").strip()
        if phone and phone not in phones:
            phones.append(phone)
    name = str(contact.get("name") or "").strip()
    if not name and emails:
        name = emails[0].split("@")[0]
    return {
        "uid": str(contact.get("uid") or uuid.uuid4()),
        "name": name,
        "emails": emails,
        "phones": phones,
    }


def load_local_contacts() -> List[Dict]:
    try:
        if not LOCAL_CONTACTS_FILE.exists():
            return []
        data = json.loads(LOCAL_CONTACTS_FILE.read_text(encoding="utf-8"))
        rows = data.get("contacts", data) if isinstance(data, dict) else data
        return [normalize_contact(c) for c in (rows or []) if isinstance(c, dict)]
    except Exception as exc:
        logger.error("Failed to load local contacts: %s", exc)
        return []


def save_local_contacts(contacts: List[Dict]) -> None:
    from core.atomic_io import atomic_write_json

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rows = [normalize_contact(c) for c in contacts]
    atomic_write_json(str(LOCAL_CONTACTS_FILE), {"contacts": rows}, indent=2)
    _contact_cache["contacts"] = rows
    _contact_cache["fetched_at"] = datetime.utcnow()


def clear_local_contacts() -> Dict[str, bool]:
    save_local_contacts([])
    return {"success": True}


def _vunesc(value: str) -> str:
    if not value:
        return value
    out = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            if nxt in ("n", "N"):
                out.append("\n")
            elif nxt in (",", ";", "\\"):
                out.append(nxt)
            else:
                out.append(nxt)
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def parse_vcards(text: str) -> List[Dict]:
    contacts = []
    for block in re.split(r"BEGIN:VCARD", text or ""):
        if not block.strip():
            continue
        contact = {"name": "", "emails": [], "phones": [], "uid": ""}
        for raw_line in block.split("\n"):
            line = raw_line.strip()
            name_part = re.sub(r"^[A-Za-z0-9-]+\.", "", line, count=1)
            if name_part.startswith("FN:") or name_part.startswith("FN;"):
                contact["name"] = _vunesc(name_part.split(":", 1)[1]) if ":" in name_part else ""
            elif name_part.startswith("EMAIL") and ":" in name_part:
                email = _vunesc(name_part.split(":", 1)[1])
                if email and email not in contact["emails"]:
                    contact["emails"].append(email)
            elif name_part.startswith("TEL") and ":" in name_part:
                phone = _vunesc(name_part.split(":", 1)[1])
                if phone and phone not in contact["phones"]:
                    contact["phones"].append(phone)
            elif name_part.startswith("UID:"):
                contact["uid"] = _vunesc(name_part[4:])
        if contact["name"] or contact["emails"]:
            contacts.append(normalize_contact(contact))
    return contacts


def _vesc(value: str) -> str:
    return (
        (value or "")
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\r", "")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def build_vcard(
    name: str,
    email: str = "",
    uid: Optional[str] = None,
    emails: Optional[List[str]] = None,
    phones: Optional[List[str]] = None,
) -> str:
    uid = uid or str(uuid.uuid4())
    email_list = [e.strip() for e in (emails if emails is not None else ([email] if email else [])) if e and e.strip()]
    phone_list = [p.strip() for p in (phones or []) if p and p.strip()]
    parts = name.strip().split()
    first = parts[0] if parts else name
    last = " ".join(parts[1:]) if len(parts) >= 2 else ""
    lines = [
        "BEGIN:VCARD",
        "VERSION:4.0",
        f"UID:{_vesc(uid)}",
        f"FN:{_vesc(name)}",
        f"N:{_vesc(last)};{_vesc(first)};;;",
    ]
    for index, item in enumerate(email_list):
        lines.append(f"EMAIL;PREF=1:{_vesc(item)}" if index == 0 else f"EMAIL:{_vesc(item)}")
    for phone in phone_list:
        lines.append(f"TEL:{_vesc(phone)}")
    lines.append("END:VCARD")
    return "\r\n".join(lines) + "\r\n"


def _abs_url(href: str) -> str:
    cfg = get_carddav_config()
    base = carddav_base_url(cfg)
    base_p = urlparse(base)
    joined = urljoin(base.rstrip("/") + "/", href or "")
    joined_p = urlparse(joined)
    if (joined_p.scheme, joined_p.netloc) != (base_p.scheme, base_p.netloc):
        joined = urlunparse((base_p.scheme, base_p.netloc, joined_p.path or "/", "", joined_p.query, ""))
    return validate_carddav_url(joined)


_ADDRESSBOOK_QUERY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<C:addressbook-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:carddav">'
    "<D:prop><D:getetag/><C:address-data/></D:prop>"
    "<C:filter/>"
    "</C:addressbook-query>"
)


def _fetch_via_report(cfg: Dict, auth) -> Optional[List[Dict]]:
    from defusedxml import ElementTree as ET

    try:
        response = httpx.request(
            "REPORT",
            cfg["url"],
            content=_ADDRESSBOOK_QUERY.encode("utf-8"),
            headers={"Content-Type": "application/xml; charset=utf-8", "Depth": "1"},
            auth=auth,
            timeout=10,
        )
        if response.status_code not in (207, 200):
            return None
        root = ET.fromstring(response.text)
        ns = {"D": "DAV:", "C": "urn:ietf:params:xml:ns:carddav"}
        out = []
        for item in root.findall("D:response", ns):
            href_el = item.find("D:href", ns)
            data_el = item.find(".//C:address-data", ns)
            if href_el is None or data_el is None or not (data_el.text or "").strip():
                continue
            parsed = parse_vcards(data_el.text)
            if not parsed:
                continue
            contact = parsed[0]
            contact["href"] = href_el.text.strip()
            out.append(contact)
        return out or None
    except Exception as exc:
        logger.warning("CardDAV REPORT failed, falling back to GET: %s", exc)
        return None


def fetch_contacts(force: bool = False) -> List[Dict]:
    fetched_at = _contact_cache.get("fetched_at")
    if not force and fetched_at:
        age = (datetime.utcnow() - fetched_at).total_seconds()
        if age < 60:
            return list(_contact_cache.get("contacts") or [])

    cfg = get_carddav_config()
    if not carddav_configured(cfg):
        contacts = load_local_contacts()
        _contact_cache["contacts"] = contacts
        _contact_cache["fetched_at"] = datetime.utcnow()
        return contacts

    try:
        cfg["url"] = carddav_base_url(cfg)
        auth = (cfg["username"], cfg["password"]) if cfg.get("username") else None
        contacts = _fetch_via_report(cfg, auth)
        if contacts is None:
            response = httpx.get(cfg["url"], auth=auth, timeout=10)
            if response.status_code != 200:
                logger.warning("CardDAV returned %s", response.status_code)
                return list(_contact_cache.get("contacts") or [])
            contacts = parse_vcards(response.text)
        _contact_cache["contacts"] = contacts
        _contact_cache["fetched_at"] = datetime.utcnow()
        return contacts
    except Exception as exc:
        logger.error("Failed to fetch contacts: %s", exc)
        return list(_contact_cache.get("contacts") or [])


def search_contacts(q: str, *, limit: int = 10) -> List[Dict]:
    term = (q or "").strip().lower()
    if not term:
        return []
    results = []
    for contact in fetch_contacts():
        if term in (contact.get("name") or "").lower():
            results.append(contact)
            continue
        if any(term in (email or "").lower() for email in contact.get("emails") or []):
            results.append(contact)
    return results[: max(1, int(limit or 10))]


def _vcard_url(uid: str) -> str:
    from urllib.parse import quote

    cfg = get_carddav_config()
    return carddav_base_url(cfg) + "/" + quote(uid, safe="") + ".vcf"


def _resolve_resource_url(uid: str) -> str:
    def lookup() -> Optional[str]:
        for contact in _contact_cache.get("contacts", []) or []:
            if contact.get("uid") == uid and contact.get("href"):
                return _abs_url(contact["href"])
        return None

    found = lookup()
    if found:
        return found
    try:
        fetch_contacts(force=True)
    except Exception:
        pass
    return lookup() or _vcard_url(uid)


def create_contact(name: str, email: str) -> bool:
    cfg = get_carddav_config()
    if not carddav_configured(cfg):
        contacts = load_local_contacts()
        email_l = (email or "").strip().lower()
        if email_l and any(email_l in [e.lower() for e in c.get("emails", [])] for c in contacts):
            return True
        contacts.append(normalize_contact({"name": name, "emails": [email]}))
        save_local_contacts(contacts)
        return True

    contact_uid = str(uuid.uuid4())
    try:
        url = carddav_base_url(cfg) + "/" + contact_uid + ".vcf"
        response = httpx.put(
            url,
            data=build_vcard(name, email, contact_uid).encode("utf-8"),
            headers={"Content-Type": "text/vcard; charset=utf-8"},
            auth=(cfg["username"], cfg["password"]) if cfg.get("username") else None,
            timeout=10,
        )
        if response.status_code in (200, 201, 204):
            invalidate_cache()
            return True
        logger.warning("CardDAV PUT returned %s: %s", response.status_code, response.text[:200])
        return False
    except Exception as exc:
        logger.error("Failed to create contact: %s", exc)
        return False


def add_contact(name: str, email: str) -> Dict:
    email = (email or "").strip()
    name = (name or "").strip() or (email.split("@")[0] if email else "")
    if not email:
        return {"success": False, "error": "Email required"}
    for contact in fetch_contacts():
        if email.lower() in [e.lower() for e in contact.get("emails", [])]:
            return {"success": True, "message": "Already exists", "contact": contact}
    return {"success": create_contact(name, email)}


def update_contact(uid: str, name: str, emails: List[str], phones: List[str]) -> bool:
    cfg = get_carddav_config()
    if not carddav_configured(cfg):
        contacts = load_local_contacts()
        found = False
        out = []
        for contact in contacts:
            if contact.get("uid") == uid:
                out.append(normalize_contact({"uid": uid, "name": name, "emails": emails, "phones": phones}))
                found = True
            else:
                out.append(contact)
        if not found:
            out.append(normalize_contact({"uid": uid, "name": name, "emails": emails, "phones": phones}))
        save_local_contacts(out)
        return True

    try:
        response = httpx.put(
            _resolve_resource_url(uid),
            data=build_vcard(name, uid=uid, emails=emails, phones=phones).encode("utf-8"),
            headers={"Content-Type": "text/vcard; charset=utf-8"},
            auth=(cfg["username"], cfg["password"]) if cfg.get("username") else None,
            timeout=10,
        )
        if response.status_code in (200, 201, 204):
            invalidate_cache()
            return True
        logger.warning("CardDAV update PUT returned %s: %s", response.status_code, response.text[:200])
        return False
    except Exception as exc:
        logger.error("Failed to update contact: %s", exc)
        return False


def delete_contact(uid: str) -> bool:
    cfg = get_carddav_config()
    if not carddav_configured(cfg):
        remaining = [c for c in load_local_contacts() if c.get("uid") != uid]
        save_local_contacts(remaining)
        return True

    try:
        response = httpx.delete(
            _resolve_resource_url(uid),
            auth=(cfg["username"], cfg["password"]) if cfg.get("username") else None,
            timeout=10,
        )
        if response.status_code in (200, 204):
            invalidate_cache()
            return True
        if response.status_code == 404:
            invalidate_cache()
            return True
        logger.warning("CardDAV DELETE returned %s: %s", response.status_code, response.text[:200])
        return False
    except Exception as exc:
        logger.error("Failed to delete contact: %s", exc)
        return False


def import_vcards(text: str) -> Dict:
    from urllib.parse import quote

    cfg = get_carddav_config()
    if not cfg.get("url"):
        parsed = parse_vcards(text)
        contacts = load_local_contacts()
        existing = {
            e.lower()
            for contact in contacts
            for e in (contact.get("emails") or [])
            if e
        }
        imported = 0
        for contact in parsed:
            emails = [e for e in (contact.get("emails") or []) if e]
            if emails and any(e.lower() in existing for e in emails):
                continue
            contacts.append(normalize_contact(contact))
            for email in emails:
                existing.add(email.lower())
            imported += 1
        if imported:
            save_local_contacts(contacts)
        return {"imported": imported, "failed": 0, "total": len(parsed)}

    try:
        base_url = carddav_base_url(cfg)
    except ValueError as exc:
        logger.warning("CardDAV import URL rejected: %s", exc)
        return {"imported": 0, "failed": 0, "total": 0, "error": str(exc)}

    auth = (cfg["username"], cfg["password"]) if cfg.get("username") else None
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    blocks = []
    for chunk in raw.split("BEGIN:VCARD"):
        chunk = chunk.strip()
        if not chunk:
            continue
        end = chunk.upper().find("END:VCARD")
        body = chunk[: end + len("END:VCARD")] if end != -1 else chunk
        blocks.append("BEGIN:VCARD\n" + body)

    imported = 0
    failed = 0
    for block in blocks:
        match = re.search(r"^UID:(.+)$", block, re.MULTILINE)
        uid = (match.group(1).strip() if match else "") or str(uuid.uuid4())
        if not match:
            if re.search(r"^VERSION:", block, re.MULTILINE):
                block = re.sub(r"(^VERSION:.*$)", r"\1\nUID:" + uid, block, count=1, flags=re.MULTILINE)
            else:
                block = block.replace("BEGIN:VCARD", f"BEGIN:VCARD\nVERSION:4.0\nUID:{uid}", 1)
        elif not re.search(r"^VERSION:", block, re.MULTILINE):
            block = block.replace("BEGIN:VCARD", "BEGIN:VCARD\nVERSION:4.0", 1)
        try:
            response = httpx.put(
                base_url + "/" + quote(uid, safe="") + ".vcf",
                data=(block.replace("\n", "\r\n") + "\r\n").encode("utf-8"),
                headers={"Content-Type": "text/vcard; charset=utf-8"},
                auth=auth,
                timeout=15,
            )
            if response.status_code in (200, 201, 204):
                imported += 1
            else:
                failed += 1
                logger.warning("Import PUT %s returned %s: %s", uid, response.status_code, response.text[:120])
        except Exception as exc:
            failed += 1
            logger.error("Import PUT %s failed: %s", uid, exc)
    if imported:
        invalidate_cache()
    return {"imported": imported, "failed": failed, "total": len(blocks)}


def import_csv_contacts(text: str) -> Dict:
    raw = (text or "").strip()
    if not raw:
        return {"imported": 0, "failed": 0, "total": 0, "error": "No CSV data found"}
    try:
        dialect = csv.Sniffer().sniff(raw[:2048])
    except Exception:
        dialect = csv.excel
    try:
        has_header = csv.Sniffer().has_header(raw[:2048])
    except Exception:
        has_header = True

    stream = io.StringIO(raw)
    rows = []
    if has_header:
        for row in csv.DictReader(stream, dialect=dialect):
            lowered = {str(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            rows.append((
                lowered.get("name") or lowered.get("full name") or lowered.get("full_name")
                or lowered.get("display name") or lowered.get("display_name") or lowered.get("fn") or "",
                lowered.get("email") or lowered.get("email address") or lowered.get("email_address")
                or lowered.get("e-mail") or lowered.get("mail") or "",
                lowered.get("phone") or lowered.get("telephone") or lowered.get("tel") or "",
            ))
    else:
        for row in csv.reader(stream, dialect=dialect):
            cols = [(c or "").strip() for c in row]
            if any(cols):
                rows.append((cols[0] if len(cols) > 0 else "", cols[1] if len(cols) > 1 else "", cols[2] if len(cols) > 2 else ""))

    imported = 0
    failed = 0
    total = 0
    existing_emails = {
        e.lower()
        for contact in fetch_contacts()
        for e in (contact.get("emails") or [])
        if e
    }
    for name, email, phone in rows:
        email = (email or "").strip()
        name = (name or "").strip() or (email.split("@")[0] if email else "")
        if not email:
            continue
        total += 1
        if email.lower() in existing_emails:
            continue
        if create_contact(name, email):
            imported += 1
            existing_emails.add(email.lower())
            if phone:
                created = next((c for c in fetch_contacts(force=True) if email.lower() in [e.lower() for e in c.get("emails", [])]), None)
                if created and created.get("uid"):
                    update_contact(created["uid"], name, [email], [phone])
        else:
            failed += 1
    if imported:
        invalidate_cache()
    return {"imported": imported, "failed": failed, "total": total}


def import_contacts(data: Dict) -> Dict:
    text = data.get("vcf") or data.get("text") or ""
    csv_text = data.get("csv") or ""
    if text.strip():
        if "BEGIN:VCARD" not in text.upper():
            return {"success": False, "error": "No vCard data found"}
        result = import_vcards(text)
    elif csv_text.strip():
        result = import_csv_contacts(csv_text)
    else:
        return {"success": False, "error": "No contact data found"}
    result["success"] = result.get("imported", 0) > 0
    return result


def contacts_to_vcf(contacts: List[Dict]) -> str:
    return "".join(
        build_vcard(
            contact.get("name") or ((contact.get("emails") or [""])[0].split("@")[0] if contact.get("emails") else "Contact"),
            uid=contact.get("uid") or str(uuid.uuid4()),
            emails=contact.get("emails") or [],
            phones=contact.get("phones") or [],
        )
        for contact in contacts
    )


def contacts_to_csv(contacts: List[Dict]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["name", "email", "phone"])
    for contact in contacts:
        emails = contact.get("emails") or [""]
        phones = contact.get("phones") or [""]
        for index in range(max(len(emails), len(phones), 1)):
            writer.writerow([
                contact.get("name") or "",
                emails[index] if index < len(emails) else "",
                phones[index] if index < len(phones) else "",
            ])
    return out.getvalue()

