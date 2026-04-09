from fastapi import APIRouter, Depends
from .endpoints import router as admin_endpoints
from .endpoints import auth_router
from security import get_current_admin_user

router = APIRouter()
router.include_router(auth_router)
router.include_router(admin_endpoints, dependencies=[Depends(get_current_admin_user)])
