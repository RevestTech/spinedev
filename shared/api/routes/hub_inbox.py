"""``/api/v2/hub/inbox`` — Hub message center (portfolio briefings, not project approvals).

Master director daily briefings and future Hub-level notices live here.
Project approvals remain on ``/api/v2/decisions`` (scope=project).
Ack/reject reuse the decision-card endpoints — same durable rows.
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Query

from shared.api.dependencies import current_user
from shared.api.routes.decisions import DecisionList, DecisionStatus, get_store
from shared.api.routes.hub_scope import is_hub_inbox_card
from shared.identity.models import User

router = APIRouter(prefix="/api/v2/hub", tags=["hub"])

InboxScope = Literal["inbox", "all"]


@router.get("/inbox", response_model=DecisionList)
async def list_hub_inbox(
    user: Annotated[User, Depends(current_user)],
    status_filter: Optional[DecisionStatus] = Query(default="pending", alias="status"),
) -> DecisionList:
    """Pending Hub-level messages (master briefings, portfolio rollups)."""
    items = await get_store().alist(status_filter=status_filter)
    inbox = [c for c in items if is_hub_inbox_card(c)]
    inbox.sort(key=lambda c: c.created_at, reverse=True)
    return DecisionList(items=inbox, total=len(inbox))
