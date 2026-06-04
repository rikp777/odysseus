"""CardDAV/local contacts routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from core.middleware import require_admin
from src.contacts import service as contacts_service


# Backwards-compatible aliases for older in-process callers. New code should
# import src.contacts.service directly.
_fetch_contacts = contacts_service.fetch_contacts
_create_contact = contacts_service.create_contact
_update_contact = contacts_service.update_contact
_delete_contact = contacts_service.delete_contact
_get_carddav_config = contacts_service.get_carddav_config
_parse_vcards = contacts_service.parse_vcards


def setup_contacts_routes():
    router = APIRouter(prefix="/api/contacts", tags=["contacts"])

    @router.get("/list")
    async def list_contacts(_admin: str = Depends(require_admin)):
        contacts = contacts_service.fetch_contacts()
        return {"contacts": contacts, "count": len(contacts)}

    @router.get("/search")
    async def search_contacts(q: str = Query(""), _admin: str = Depends(require_admin)):
        term = (q or "").strip().lower()
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
        email = (data.get("email") or "").strip()
        name = (data.get("name") or "").strip() or (email.split("@")[0] if email else "")
        if not email:
            return {"success": False, "error": "Email required"}
        for contact in _fetch_contacts():
            if email.lower() in [e.lower() for e in contact.get("emails", [])]:
                return {"success": True, "message": "Already exists", "contact": contact}
        return {"success": _create_contact(name, email)}

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
        return contacts_service.update_carddav_config(data)

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
