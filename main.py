from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from dotenv import load_dotenv

# 加载 .env 环境变量
load_dotenv()

from admin import router as admin_router
from api import router as client_api_router
from database import engine
from models import Base

app = FastAPI(title="维乐会所预约系统 API")

# 静态资源挂载 (图片上传目录)
upload_dir = os.path.join(os.path.dirname(__file__), "uploads")
if not os.path.exists(upload_dir):
    os.makedirs(upload_dir)
app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")

# 🌟 挂载前端 dist 目录
dist_dir = os.path.join(os.path.dirname(__file__), "dist")
if os.path.exists(dist_dir):
    # 挂载 assets 目录 (JS/CSS)
    assets_dir = os.path.join(dist_dir, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
    
    # 挂载其他静态资源 (favicon, icons 等)
    app.mount("/dist", StaticFiles(directory=dist_dir), name="dist")

# 注册路由
app.include_router(admin_router, prefix="/admin", tags=["后台管理"])
app.include_router(client_api_router, prefix="/api", tags=["客户端接口"])

@app.on_event("startup")
def ensure_tables():
    Base.metadata.create_all(bind=engine)

@app.get("/")
async def root():
    index_path = os.path.join(os.path.dirname(__file__), "dist", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Welcome to Massage Booking API"}
