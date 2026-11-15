"""v1 API의 업무별 라우터를 등록한다."""

from fastapi import APIRouter

from app.routers import (
    ai,
    auth,
    consultations,
    deletion,
    handover,
    history,
    matching,
    public,
    requests,
    reservations,
    technicians,
    work,
)


api_router = APIRouter(prefix="/v1")
api_router.include_router(auth.router)
api_router.include_router(public.router)
api_router.include_router(requests.router)
api_router.include_router(history.router)
api_router.include_router(ai.router)
api_router.include_router(technicians.router)
api_router.include_router(matching.router)
api_router.include_router(consultations.router)
api_router.include_router(reservations.router)
api_router.include_router(work.router)
api_router.include_router(handover.router)
api_router.include_router(deletion.router)
