from fastapi import APIRouter

from meetup_bot.api.attendance import router as attendance_router
from meetup_bot.api.events import router as events_router

router = APIRouter()
router.include_router(events_router)
router.include_router(attendance_router)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
