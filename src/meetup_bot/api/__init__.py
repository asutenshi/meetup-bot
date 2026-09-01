from fastapi import APIRouter

from meetup_bot.api.attendance import router as attendance_router
from meetup_bot.api.events import router as events_router
from meetup_bot.api.home import router as home_router
from meetup_bot.api.project_settings import router as project_settings_router

router = APIRouter()
router.include_router(events_router)
router.include_router(home_router)
router.include_router(attendance_router)
router.include_router(project_settings_router)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
