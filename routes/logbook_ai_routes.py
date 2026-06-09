"""Daily Logbook AI API routes."""

from collections.abc import Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.database import SessionLocal
from src.logbook import ai as logbook_ai
from src.logbook import repository as logbook_repo
from src.logbook import serializers as logbook_serializers
from src.logbook.schemas import LogbookAIAssist


def register_logbook_ai_routes(
    router: APIRouter,
    *,
    owner_func: Callable[[Request], str],
    session_factory: Callable[[], object] = SessionLocal,
) -> None:
    @router.get("/ai/status")
    def ai_status(request: Request):
        owner = owner_func(request)
        return logbook_ai.ai_status(owner)

    @router.post("/ai/estimate")
    def ai_estimate(request: Request, body: LogbookAIAssist):
        owner = owner_func(request)
        return logbook_ai.estimate_ai_usage(owner, body)

    @router.get("/ai/usage-summary")
    def ai_usage_summary(request: Request):
        owner = owner_func(request)
        return logbook_ai.ai_usage_summary(owner)

    @router.post("/ai/assist")
    async def ai_assist(request: Request, body: LogbookAIAssist):
        owner = owner_func(request)
        return await logbook_ai.run_ai_assist(owner, body)

    @router.post("/ai/analyze-entry/{entry_id}")
    async def analyze_entry(request: Request, entry_id: str):
        owner = owner_func(request)
        db = session_factory()
        try:
            entry = logbook_repo.load_entry_or_404(db, owner, entry_id)
            payload = LogbookAIAssist(
                entry_date=entry.entry_date,
                content=entry.content or "",
                mode="extract_all",
                locale="en",
                current_entry=logbook_serializers.entry_to_dict(entry),
            )
            result = await logbook_ai.run_ai_assist(owner, payload)
            if isinstance(result, JSONResponse):
                return result
            updated_people = logbook_ai.store_ai_person_suggestion_details(
                db,
                owner,
                entry,
                result.get("people_suggestions") or [],
            )
            stored = logbook_ai.store_ai_connection_suggestions(
                db,
                owner,
                entry,
                result.get("connection_suggestions") or [],
            )
            db.commit()
            result["updated_people"] = [logbook_serializers.person_to_dict(person) for person in updated_people]
            result["stored_connections"] = [logbook_serializers.connection_to_dict(c) for c in stored]
            return result
        finally:
            db.close()
