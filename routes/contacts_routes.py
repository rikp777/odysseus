"""CardDAV/local contacts routes.

The implementation lives in ``src.contacts.service`` so routes, tools, email,
and Logbook do not maintain separate copies of the same CardDAV/local-contact
logic. This module keeps the historical route-private helper names as thin
wrappers for tests and older in-process callers.
"""

from __future__ import annotations

import inspect
import os
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote, urljoin, urlparse, urlunparse

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from core.middleware import require_admin
from src.contacts import service as contacts_service
from src.url_safety import check_outbound_url


DATA_DIR = contacts_service.DATA_DIR
SETTINGS_FILE = contacts_service.SETTINGS_FILE
LOCAL_CONTACTS_FILE = contacts_service.LOCAL_CONTACTS_FILE
_contact_cache = contacts_service._contact_cache


def _sync_service_paths() -> None:
    """Mirror monkeypatched legacy route paths into the shared service."""
    data_dir = Path(DATA_DIR)
    settings_file = Path(SETTINGS_FILE)
    contacts_file = Path(LOCAL_CONTACTS_FILE)
    if (
        contacts_service.DATA_DIR != data_dir
        or contacts_service.SETTINGS_FILE != settings_file
        or contacts_service.LOCAL_CONTACTS_FILE != contacts_file
    ):
        contacts_service.DATA_DIR = data_dir
        contacts_service.SETTINGS_FILE = settings_file
        contacts_service.LOCAL_CONTACTS_FILE = contacts_file
        contacts_service.invalidate_cache()


def _load_settings() -> Dict:
    _sync_service_paths()
    return contacts_service.load_settings()


def _save_settings(settings: Dict) -> None:
    _sync_service_paths()
    contacts_service.save_settings(settings)


def _get_carddav_config() -> Dict[str, str]:
    _sync_service_paths()
    return contacts_service.get_carddav_config()


def _carddav_configured(cfg: Optional[Dict] = None) -> bool:
    _sync_service_paths()
    return contacts_service.carddav_configured(cfg)


def _validate_carddav_url(url: str) -> str:
    cleaned = (url if isinstance(url, str) else "").strip().rstrip("/")
    ok, reason = check_outbound_url(
        cleaned,
        block_private=os.getenv("CARDDAV_BLOCK_PRIVATE_IPS", "false").lower() == "true",
    )
    if not ok:
        raise ValueError(f"Rejected CardDAV URL: {reason}")
    return cleaned


def _carddav_base_url(cfg: Dict) -> str:
    return _validate_carddav_url(cfg.get("url") or "")


def _abs_url(href: str) -> str:
    cfg = _get_carddav_config()
    base = _carddav_base_url(cfg)
    base_p = urlparse(base)
    joined = urljoin(base.rstrip("/") + "/", href or "")
    joined_p = urlparse(joined)
    if (joined_p.scheme, joined_p.netloc) != (base_p.scheme, base_p.netloc):
        joined = urlunparse((base_p.scheme, base_p.netloc, joined_p.path or "/", "", joined_p.query, ""))
    return _validate_carddav_url(joined)


def _vcard_url(uid: str) -> str:
    cfg = _get_carddav_config()
    return _carddav_base_url(cfg) + "/" + quote(uid, safe="") + ".vcf"


def _normalize_contact(contact: Dict) -> Dict:
    _sync_service_paths()
    return contacts_service.normalize_contact(contact)


def _load_local_contacts() -> List[Dict]:
    _sync_service_paths()
    return contacts_service.load_local_contacts()


def _save_local_contacts(contacts: List[Dict]) -> None:
    _sync_service_paths()
    contacts_service.save_local_contacts(contacts)


def _parse_vcards(text: str) -> List[Dict]:
    _sync_service_paths()
    return contacts_service.parse_vcards(text)


def _build_vcard(
    name: str,
    email: str = "",
    uid: Optional[str] = None,
    emails: Optional[List[str]] = None,
    phones: Optional[List[str]] = None,
    address: Optional[str] = None,
) -> str:
    _sync_service_paths()
    return contacts_service.build_vcard(
        name,
        email,
        uid=uid,
        emails=emails,
        phones=phones,
        address=address,
    )


def _fetch_contacts(force: bool = False) -> List[Dict]:
    _sync_service_paths()
    return contacts_service.fetch_contacts(force=force)


def _resolve_resource_url(uid: str) -> str:
    _sync_service_paths()
    return contacts_service._resolve_resource_url(uid)


def _create_contact(name: str, email: str, address: str = "") -> bool:
    _sync_service_paths()
    return contacts_service.create_contact(name, email, address)


def _update_contact(uid: str, name: str, emails: List[str], phones: List[str], address: str = "") -> bool:
    _sync_service_paths()
    return contacts_service.update_contact(uid, name, emails, phones, address)


def _delete_contact(uid: str) -> bool:
    _sync_service_paths()
    return contacts_service.delete_contact(uid)


def _import_vcards(text: str) -> Dict:
    _sync_service_paths()
    return contacts_service.import_vcards(text)


def _import_csv_contacts(text: str) -> Dict:
    _sync_service_paths()
    return contacts_service.import_csv_contacts(text)


def _contacts_to_vcf(contacts: List[Dict]) -> str:
    _sync_service_paths()
    return contacts_service.contacts_to_vcf(contacts)


def _contacts_to_csv(contacts: List[Dict]) -> str:
    _sync_service_paths()
    return contacts_service.contacts_to_csv(contacts)


def _call_create_contact(name: str, email: str, address: str) -> bool:
    try:
        params = inspect.signature(_create_contact).parameters
        accepts_address = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        accepts_address = accepts_address or len(params) >= 3
    except (TypeError, ValueError):
        accepts_address = True
    if accepts_address:
        return _create_contact(name, email, address)
    return _create_contact(name, email)  # type: ignore[misc]


def _call_update_contact(uid: str, name: str, emails: List[str], phones: List[str], address: str) -> bool:
    try:
        params = inspect.signature(_update_contact).parameters
        accepts_address = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        accepts_address = accepts_address or len(params) >= 5
    except (TypeError, ValueError):
        accepts_address = True
    if accepts_address:
        return _update_contact(uid, name, emails, phones, address)
    return _update_contact(uid, name, emails, phones)  # type: ignore[misc]


def setup_contacts_routes():
    router = APIRouter(prefix="/api/contacts", tags=["contacts"])

    @router.get("/list")
    async def list_contacts(_admin: str = Depends(require_admin)):
        contacts = _fetch_contacts()
        return {"contacts": contacts, "count": len(contacts)}

    @router.get("/search")
    async def search_contacts(q: str = Query(""), _admin: str = Depends(require_admin)):
        term = (q or "").lower()
        if not term:
            return {"results": []}
        results = []
        for contact in _fetch_contacts():
            if term in (contact.get("name") or "").lower():
                results.append(contact)
                continue
            if any(term in (email or "").lower() for email in contact.get("emails") or []):
                results.append(contact)
        return {"results": results[:10]}

    @router.post("/add")
    async def add_contact(data: dict, _admin: str = Depends(require_admin)):
        name = (data.get("name") or "").strip()
        email = (data.get("email") or "").strip()
        phone = (data.get("phone") or "").strip()
        address = (data.get("address") or "").strip()
        if not email:
            return {"success": False, "error": "Email required"}

        for contact in _fetch_contacts():
            if email.lower() in [e.lower() for e in contact.get("emails") or []]:
                return {"success": True, "message": "Already exists", "contact": contact}

        if not name:
            name = email.split("@")[0]

        ok = _call_create_contact(name, email, address)
        if ok and phone:
            try:
                fresh = _fetch_contacts(force=True)
                created = next(
                    (
                        contact
                        for contact in fresh
                        if name == contact.get("name")
                        and email.lower() in [e.lower() for e in contact.get("emails") or []]
                    ),
                    None,
                )
                if created and created.get("uid"):
                    _call_update_contact(
                        created["uid"],
                        name,
                        created.get("emails") or [email],
                        [phone],
                        address,
                    )
            except Exception:
                pass
        return {"success": ok}

    @router.post("/import")
    async def import_contacts(data: dict, _admin: str = Depends(require_admin)):
        _sync_service_paths()
        return contacts_service.import_contacts(data)

    @router.get("/export")
    async def export_contacts(
        format: str = Query("vcf", pattern="^(vcf|csv)$"),
        _admin: str = Depends(require_admin),
    ):
        contacts = _fetch_contacts(force=True)
        if format == "csv":
            content = _contacts_to_csv(contacts)
            media_type = "text/csv; charset=utf-8"
            filename = "odysseus-contacts.csv"
        else:
            content = _contacts_to_vcf(contacts)
            media_type = "text/vcard; charset=utf-8"
            filename = "odysseus-contacts.vcf"
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get("/config")
    async def get_config(_admin: str = Depends(require_admin)):
        _sync_service_paths()
        return contacts_service.masked_carddav_config()

    @router.put("/config")
    async def update_config(data: dict, _admin: str = Depends(require_admin)):
        try:
            _sync_service_paths()
            return contacts_service.update_carddav_config(data)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @router.delete("/clear")
    async def clear_contacts(_admin: str = Depends(require_admin)):
        _sync_service_paths()
        return contacts_service.clear_local_contacts()

    @router.put("/{uid}")
    async def edit_contact(uid: str, data: dict, _admin: str = Depends(require_admin)):
        name = (data.get("name") or "").strip()
        emails = data.get("emails")
        phones = data.get("phones")
        if emails is None and data.get("email"):
            emails = [data["email"]]
        emails = [e.strip() for e in (emails or []) if e and e.strip()]
        phones = [p.strip() for p in (phones or []) if p and p.strip()]
        address = (data.get("address") or "").strip()
        if not name and not emails and not address:
            return {"success": False, "error": "Name, email, or address required"}
        if not name and emails:
            name = emails[0].split("@")[0]
        return {"success": _call_update_contact(uid, name, emails, phones, address)}

    @router.delete("/{uid}")
    async def delete_contact(uid: str, _admin: str = Depends(require_admin)):
        if not uid:
            return {"success": False, "error": "UID required"}
        return {"success": _delete_contact(uid)}

    return router
