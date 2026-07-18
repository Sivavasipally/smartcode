### FastAPI skill
- Pydantic v2 models for request/response; `response_model` on every route.
- Use APIRouter per resource; dependency injection via `Depends` for auth/db.
- async def endpoints when I/O bound; raise HTTPException with proper status codes.
- Status codes explicit (`status_code=201` on create); tags for OpenAPI grouping.
