"""CardDAV/local contacts routes."""

from __future__ import annotations

import os
from urllib.parse import quote, urljoin, urlparse, urlunparse

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from core.middleware import require_admin
from src.contacts import service as contacts_service
from src.url_safety import check_outbound_url


# Backwards-compatible aliases for older in-process callers. New code should
# import src.contacts.service directly.
_fetch_contacts = contacts_service.fetch_contacts
_create_contact = contacts_service.create_contact
_update_contact = contacts_service.update_contact
_delete_contact = contacts_service.delete_contact
_get_carddav_config = contacts_service.get_carddav_config
_parse_vcards = contacts_service.parse_vcards


def _validate_carddav_url(url: str) -> str:
    cleaned = (url if isinstance(url, str) else "").strip().rstrip("/")
    ok, reason = check_outbound_url(
        cleaned,
        block_private=os.getenv("CARDDAV_BLOCK_PRIVATE_IPS", "false").lower() == "true",
    )
    if not ok:
        raise ValueError(f"Rejected CardDAV URL: {reason}")
    return cleaned


def _carddav_base_url(cfg: dict) -> str:
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


def setup_contacts_routes():
    router = APIRouter(prefix="/api/contacts", tags=["contacts"])

    @router.get("/list")
    async def list_contacts(_admin: str = Depends(require_admin)):
        contacts = contacts_service.fetch_contacts()
        return {"contacts": contacts, "count": len(contacts)}

    @router.get("/search")
    async def search_contacts(q: str = Query(""), _admin: str = Depends(require_admin)):
        return {"results": contacts_service.search_contacts(q)}

    @router.post("/add")
    async def add_contact(data: dict, _admin: str = Depends(require_admin)):
        return contacts_service.add_contact(data.get("name") or "", data.get("email") or "")

    @router.post("/import")
    async def import_contacts(data: dict, _admin: str = Depends(require_admin)):
        return contacts_service.import_contacts(data)

    @router.get("/export")
    async def export_contacts(
        format: str = Query("vcf", pattern="^(vcf|csv)$"),
        _admin: str = Depends(require_admin),
    ):
        contacts = contacts_service.fetch_contacts(force=True)
        if format == "csv":
            content = contacts_service.contacts_to_csv(contacts)
            media_type = "text/csv; charset=utf-8"
            filename = "odysseus-contacts.csv"
        else:
            content = contacts_service.contacts_to_vcf(contacts)
            media_type = "text/vcard; charset=utf-8"
            filename = "odysseus-contacts.vcf"
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get("/config")
    async def get_config(_admin: str = Depends(require_admin)):
        return contacts_service.masked_carddav_config()

    @router.put("/config")
    async def update_config(data: dict, _admin: str = Depends(require_admin)):
        try:
            return contacts_service.update_carddav_config(data)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @router.delete("/clear")
    async def clear_contacts(_admin: str = Depends(require_admin)):
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
        if not name and not emails:
            return {"success": False, "error": "Name or email required"}
        if not name and emails:
            name = emails[0].split("@")[0]
        return {"success": contacts_service.update_contact(uid, name, emails, phones)}

    @router.delete("/{uid}")
    async def delete_contact(uid: str, _admin: str = Depends(require_admin)):
        if not uid:
            return {"success": False, "error": "UID required"}
        return {"success": contacts_service.delete_contact(uid)}

    return router
