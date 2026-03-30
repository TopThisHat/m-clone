from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.models.client_lookup import ClientLookupRequest, LookupResult
from app.agent.client_resolver import resolve_client

router = APIRouter(prefix="/api", tags=["client-lookup"])


@router.post("/client-lookup", response_model=LookupResult)
async def post_client_lookup(
    body: ClientLookupRequest,
    user=Depends(get_current_user),
) -> LookupResult:
    """Look up a client's GWM ID by name using fuzzy matching and LLM adjudication."""
    return await resolve_client(
        name=body.name,
        company=body.company,
        context=body.context,
    )
