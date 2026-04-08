from fastapi import APIRouter
from .endpoints import router as admin_endpoints

router = APIRouter()
router.include_router(admin_endpoints)
