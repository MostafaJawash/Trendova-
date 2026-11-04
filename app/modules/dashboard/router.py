from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import admin
from app.core.schemas import ERROR_RESPONSES
from app.modules.dashboard.schemas import DashboardOut
from app.modules.dashboard import service
router=APIRouter(prefix='/dashboard',tags=['dashboard'],responses=ERROR_RESPONSES)
@router.get('/stats',response_model=DashboardOut,summary='Dashboard statistics',description='Admin totals, revenue, trends and top products.')
def stats(_=Depends(admin),db:Session=Depends(get_db)):return service.stats(db)
