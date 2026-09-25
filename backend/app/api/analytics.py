"""Analytics query API + dashboard Copilot.

``POST /analytics/query`` takes a typed ``AnalyticsQuery``; ``POST /analytics/ask``
takes a plain-language question, parses it deterministically and runs the same
query. Agents are scoped to their own leads; owners/admins see the workspace.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import RequestContext, WorkspaceRole, get_request_context
from app.modules.analytics.queries import (
    SUGGESTED_QUESTIONS,
    AnalyticsQuery,
    parse_question,
    run_query,
)

router = APIRouter()


def _scoped(q: AnalyticsQuery, context: RequestContext) -> AnalyticsQuery:
    if context.role in (WorkspaceRole.OWNER, WorkspaceRole.ADMIN):
        return q
    return q.model_copy(update={"broker_id": context.broker_id or "__none__"})


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=50)


@router.get("/questions")
async def suggested_questions(context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    return {"questions": SUGGESTED_QUESTIONS}


@router.post("/query")
async def query(body: AnalyticsQuery, context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    result = await run_query(_scoped(body, context), workspace_id=context.workspace_id)
    return result.model_dump(mode="json")


@router.post("/ask")
async def ask(body: AskIn, context: RequestContext = Depends(get_request_context)) -> dict[str, Any]:
    q = parse_question(body.question, default_limit=body.limit)
    result = await run_query(_scoped(q, context), workspace_id=context.workspace_id)
    return {"question": body.question, **result.model_dump(mode="json")}
