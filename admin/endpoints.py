from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Query
import os
import shutil
import uuid
import httpx
import json
from qcloud_cos import CosConfig
from qcloud_cos import CosS3Client
from datetime import datetime, timedelta
from datetime import date as date_type
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import List, Optional
from database import get_db
from models import Service, Technician, AdminUser, Captcha, Booking, TechnicianSchedule, MarketingSource, Carousel, ShopInfo
from schemas import (
    ServiceCreate, ServiceUpdate, ServiceResponse,
    TechnicianCreate, TechnicianUpdate, TechnicianResponse,
    LoginRequest, CaptchaResponse, TokenResponse, BookingResponse, BookingStatusUpdate, BookingEditUpdate, PageResponse,
    TechnicianScheduleUpsert, TechnicianScheduleResponse,
    MarketingSourceCreate, MarketingSourceUpdate, MarketingSourceResponse,
    CarouselCreate, CarouselUpdate, CarouselResponse,
    ShopInfoUpdate, ShopInfoResponse
)
from captcha_utils import generate_captcha
from security import verify_password, create_access_token


router = APIRouter()
auth_router = APIRouter()

# --- 登录相关接口 ---

@auth_router.get("/captcha", response_model=CaptchaResponse)
async def get_captcha(db: Session = Depends(get_db)):
    """获取图形验证码并存入数据库"""
    captcha_id = str(uuid.uuid4())
    code, base64_image = generate_captcha()
    
    # 存入数据库，设置 5 分钟过期
    expire_at = datetime.utcnow() + timedelta(minutes=5)
    db_captcha = Captcha(id=captcha_id, code=code.upper(), expire_at=expire_at)
    db.add(db_captcha)
    db.commit()
    
    return {
        "captcha_id": captcha_id,
        "captcha_image": base64_image
    }

@auth_router.post("/login", response_model=TokenResponse)
async def login(login_in: LoginRequest, db: Session = Depends(get_db)):
    """管理员登录 (包含验证码校验和密码哈希校验)"""
    # 1. 验证码校验 (从数据库查询)
    db_captcha = db.query(Captcha).filter(
        Captcha.id == login_in.captcha_id,
        Captcha.is_used == False,
        Captcha.expire_at > datetime.utcnow()
    ).first()
    
    if not db_captcha or db_captcha.code.upper() != login_in.captcha_code.upper():
        raise HTTPException(status_code=400, detail="验证码错误或已过期")
    
    # 标记验证码已使用
    db_captcha.is_used = True
    db.commit()

    # 2. 用户名密码校验
    admin = db.query(AdminUser).filter(AdminUser.username == login_in.username).first()
    if not admin or not verify_password(login_in.password, admin.hashed_password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not admin.is_active:
        raise HTTPException(status_code=403, detail="账户已禁用")

    # 3. 生成真实 JWT Token
    access_token = create_access_token(data={"sub": admin.username, "id": admin.id})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "username": admin.username,
        "permissions": ["schedules:manage"]
    }

# --- 文件上传接口 (COS SDK 版本) ---

async def get_wechat_access_token():
    """获取微信接口调用凭证 access_token"""
    app_id = os.getenv("WECHAT_APP_ID")
    app_secret = os.getenv("WECHAT_APP_SECRET")
    if not app_id or not app_secret:
        print("Warning: WECHAT_APP_ID or WECHAT_APP_SECRET not set.")
        return None
        
    url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={app_id}&secret={app_secret}"
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.get(url, timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                if "access_token" in data:
                    return data["access_token"]
                else:
                    print(f"Get Access Token Error: {data}")
            else:
                print(f"Get Access Token HTTP Error: {response.status_code}")
        except Exception as e:
            print(f"Get Access Token Exception: {str(e)}")
    return None

async def get_wx_upload_params(filename: str):
    """从微信云托管获取上传授权，获取临时密钥信息"""
    access_token = await get_wechat_access_token()
    if not access_token:
        print("Failed to get wechat access_token.")
        return None
        
    # 微信云开发获取上传文件链接 API (使用 access_token)
    url = f"https://api.weixin.qq.com/tcb/uploadfile?access_token={access_token}"
    
    # 获取环境 ID (通常从环境变量获取)
    env_id = os.environ.get("WX_CLOUD_ENV") or os.environ.get("ENV_ID")
    if not env_id:
        # 如果没有配置环境 ID，退回到本地存储或报错
        print("Warning: WX_CLOUD_ENV not set, file will not be uploaded to cloud storage.")
        return None

    path = f"uploads/{datetime.now().strftime('%Y%m%d')}/{uuid.uuid4()}_{filename}"
    
    payload = {
        "env": env_id,
        "path": path
    }
    async with httpx.AsyncClient(verify=False) as client:
        try:
            response = await client.post(url, json=payload, timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                if data.get("errcode") == 0:
                    return {
                        "url": data["url"],
                        "token": data["token"],
                        "authorization": data["authorization"],
                        "file_id": data["file_id"],
                        "cos_file_id": data["cos_file_id"],
                        "path": path,
                        "env": env_id
                    }
                else:
                    print(f"WX Upload Auth Error: {data}")
            else:
                print(f"WX Upload Auth HTTP Error: {response.status_code}")
        except Exception as e:
            print(f"WX Upload Auth Exception: {str(e)}")
    return None

def parse_authorization(auth_str: str):
    """解析 authorization 字符串获取 SecretId 和 SecretKey"""
    # auth_str 格式通常为: q-sign-algorithm=sha1&q-ak=SecretId&q-sign-time=...&q-key-time=...&q-header-list=...&q-url-param-list=...&q-signature=...
    # 或者对于微信云开发返回的特殊 auth 格式进行适配
    import urllib.parse
    params = urllib.parse.parse_qs(auth_str)
    
    secret_id = params.get('q-ak', [''])[0]
    # 注意：微信云开发直接获取上传链接的接口，authorization 可能不包含完整的 secret_key
    # 通常使用 COS SDK 建议使用 sts 接口 (获取临时密钥)
    # 但由于微信云托管 /tcb/uploadfile 返回的是组装好的 authorization 签名，直接使用 SDK 的简单 put_object 可能需要直接传递 token 和 signature
    # 或者我们可以直接手动发起 PUT 请求，因为 SDK 更适合完整的 SecretId/SecretKey 鉴权
    pass

@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """直接上传文件到微信云托管对象存储，不保留本地副本"""
    
    ext = os.path.splitext(file.filename)[1]
    filename = f"{uuid.uuid4()}{ext}"
    
    # 读取文件内容为二进制流
    content = await file.read()

    # 微信云托管对象存储配置
    bucket = "7072-prod-5gm2le1c2f0d8bb2-1420164044"
    region = "ap-shanghai"
    
    # 优先使用 SDK 直接上传 (利用云托管免密钥环境)
    secret_id = os.environ.get('TENCENTCLOUD_SECRETID')
    secret_key = os.environ.get('TENCENTCLOUD_SECRETKEY')
    token = os.environ.get('TENCENTCLOUD_SESSIONTOKEN')

    if secret_id and secret_key:
        try:
            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)
            client = CosS3Client(config)
            
            key = f"uploads/{datetime.now().strftime('%Y%m%d')}/{filename}"
            
            client.put_object(
                Bucket=bucket,
                Body=content,
                Key=key,
                EnableMD5=False
            )
            
            # 生成访问链接 (使用用户要求的 bucket 作为前缀)
            public_url = f"https://{bucket}.tcb.qcloud.la/{key}"
            return {"url": public_url}
            
        except Exception as e:
            print(f"Cloud Storage SDK Upload Error: {str(e)}")

    # 兜底：使用微信云托管上传授权接口 (适用于本地调试且未配置环境变量时)
    auth_params = await get_wx_upload_params(filename)
    if auth_params:
        try:
            files = {
                "key": (None, auth_params["path"]),
                "Signature": (None, auth_params["authorization"]),
                "x-cos-security-token": (None, auth_params["token"]),
                "x-cos-meta-fileid": (None, auth_params["cos_file_id"]),
                "file": (filename, content, file.content_type)
            }
            
            async with httpx.AsyncClient(verify=False) as client:
                res = await client.post(auth_params["url"], files=files, timeout=30.0)
                if res.status_code == 204:
                    path = auth_params["path"]
                    # 🌟 统一使用 bucket 作为前缀的域名
                    public_url = f"https://{bucket}.tcb.qcloud.la/{path}"
                    return {"url": public_url}
        except Exception as e:
            print(f"Fallback Upload Exception: {str(e)}")

    raise HTTPException(status_code=500, detail="文件上传失败，请检查微信云托管配置")

# --- 服务管理 (CRUD) ---

@router.get("/services", response_model=List[ServiceResponse])
async def get_services(db: Session = Depends(get_db)):
    """获取所有服务项目"""
    services = db.query(Service).order_by(Service.sort_order.desc(), Service.id.desc()).all()
    return services

@router.get("/services/{service_id}", response_model=ServiceResponse)
async def get_service(service_id: int, db: Session = Depends(get_db)):
    """获取单个服务项目详情"""
    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="服务项目不存在")
    return service

@router.post("/services", response_model=ServiceResponse)
async def create_service(service_in: ServiceCreate, db: Session = Depends(get_db)):
    """新增服务项目"""
    db_service = Service(**service_in.dict())
    db.add(db_service)
    db.commit()
    db.refresh(db_service)
    return db_service

@router.put("/services/{service_id}", response_model=ServiceResponse)
async def update_service(service_id: int, service_in: ServiceUpdate, db: Session = Depends(get_db)):
    """修改服务项目"""
    db_service = db.query(Service).filter(Service.id == service_id).first()
    if not db_service:
        raise HTTPException(status_code=404, detail="服务项目不存在")
    
    # 更新提供的字段
    update_data = service_in.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_service, key, value)
    
    db.commit()
    db.refresh(db_service)
    return db_service

@router.delete("/services/{service_id}")
async def delete_service(service_id: int, db: Session = Depends(get_db)):
    """删除服务项目"""
    db_service = db.query(Service).filter(Service.id == service_id).first()
    if not db_service:
        raise HTTPException(status_code=404, detail="服务项目不存在")
    
    db.delete(db_service)
    db.commit()
    return {"message": f"服务项目 {service_id} 已成功删除"}

# --- 技师管理 (CRUD) ---

@router.get("/technicians", response_model=List[TechnicianResponse])
async def get_technicians(db: Session = Depends(get_db)):
    """获取所有技师列表"""
    return db.query(Technician).order_by(Technician.sort_order.desc(), Technician.id.desc()).all()

@router.get("/technicians/{tech_id}", response_model=TechnicianResponse)
async def get_technician(tech_id: int, db: Session = Depends(get_db)):
    """获取技师详情"""
    tech = db.query(Technician).filter(Technician.id == tech_id).first()
    if not tech:
        raise HTTPException(status_code=404, detail="技师不存在")
    return tech

@router.post("/technicians", response_model=TechnicianResponse)
async def create_technician(tech_in: TechnicianCreate, db: Session = Depends(get_db)):
    """新增技师并关联服务"""
    # 提取服务ID列表
    service_ids = tech_in.service_ids
    # 移除 service_ids 以便创建 Technician 对象
    tech_data = tech_in.dict(exclude={"service_ids"})
    
    db_tech = Technician(**tech_data)
    
    # 关联服务项目
    if service_ids:
        services = db.query(Service).filter(Service.id.in_(service_ids)).all()
        db_tech.services = services
        
    db.add(db_tech)
    db.commit()
    db.refresh(db_tech)
    return db_tech

@router.put("/technicians/{tech_id}", response_model=TechnicianResponse)
async def update_technician(tech_id: int, tech_in: TechnicianUpdate, db: Session = Depends(get_db)):
    """更新技师资料及服务关联"""
    db_tech = db.query(Technician).filter(Technician.id == tech_id).first()
    if not db_tech:
        raise HTTPException(status_code=404, detail="技师不存在")
    
    # 更新基本信息
    update_data = tech_in.dict(exclude_unset=True, exclude={"service_ids"})
    for key, value in update_data.items():
        setattr(db_tech, key, value)
    
    # 更新服务关联
    if tech_in.service_ids is not None:
        services = db.query(Service).filter(Service.id.in_(tech_in.service_ids)).all()
        db_tech.services = services
        
    db.commit()
    db.refresh(db_tech)
    return db_tech

@router.delete("/technicians/{tech_id}")
async def delete_technician(tech_id: int, db: Session = Depends(get_db)):
    """删除技师"""
    db_tech = db.query(Technician).filter(Technician.id == tech_id).first()
    if not db_tech:
        raise HTTPException(status_code=404, detail="技师不存在")
    
    db.delete(db_tech)
    db.commit()
    return {"message": f"技师 {tech_id} 已成功删除"}


@router.get("/schedules", response_model=List[TechnicianScheduleResponse])
async def list_schedules(
    technician_id: Optional[int] = None,
    service_id: Optional[int] = None,
    start_date: Optional[date_type] = None,
    end_date: Optional[date_type] = None,
    db: Session = Depends(get_db),
):
    query = db.query(TechnicianSchedule)
    if technician_id is not None:
        query = query.filter(TechnicianSchedule.technician_id == technician_id)
    if service_id is not None and service_id != 0:
        query = query.filter(TechnicianSchedule.service_id == service_id)
    if start_date is not None:
        query = query.filter(TechnicianSchedule.schedule_date >= start_date)
    if end_date is not None:
        query = query.filter(TechnicianSchedule.schedule_date <= end_date)
    return query.order_by(TechnicianSchedule.schedule_date.desc(), TechnicianSchedule.id.desc()).all()


@router.get("/schedules/{technician_id}/{service_id}/{schedule_date}", response_model=TechnicianScheduleResponse)
async def get_schedule(
    technician_id: int,
    service_id: int,
    schedule_date: date_type,
    db: Session = Depends(get_db),
):
    # Fetch schedule for this specific service
    filter_service_id = service_id
    if service_id == 0:
        # 如果是查询"全部项目"，尝试找任意一个已有的排班作为参考
        first_s = db.query(TechnicianSchedule).filter(
            TechnicianSchedule.technician_id == technician_id,
            TechnicianSchedule.schedule_date == schedule_date
        ).first()
        filter_service_id = first_s.service_id if first_s else 0

    schedule = (
        db.query(TechnicianSchedule)
        .filter(
            TechnicianSchedule.technician_id == technician_id,
            TechnicianSchedule.service_id == filter_service_id,
            TechnicianSchedule.schedule_date == schedule_date,
        )
        .first()
    )
    
    # 🌟 优化：不再根据其他项目的排班返回 occupied_times，而是根据实际预约 (Booking) 返回
    # 这样管理员就可以为同一个技师的多个项目排班相同的时间段了
    bookings = (
        db.query(Booking)
        .filter(
            Booking.technician_id == technician_id,
            Booking.booking_date == schedule_date,
            Booking.status != "cancelled",
        )
        .all()
    )
    occupied_times = []
    for b in bookings:
        if isinstance(b.booking_times, list):
            occupied_times.extend(b.booking_times)
    occupied_times = list(set(occupied_times))
    occupied_times.sort()

    if not schedule:
        return {
            "id": 0,
            "technician_id": technician_id,
            "service_id": service_id,
            "schedule_date": schedule_date,
            "available_times": [],
            "occupied_times": occupied_times,
            "created_at": datetime.utcnow(),
            "updated_at": None,
        }
    
    # Use Pydantic/dict to add occupied_times since it's not a model field
    res = {
        "id": schedule.id if schedule else 0,
        "technician_id": technician_id,
        "service_id": service_id, # 始终返回前端请求的 service_id
        "schedule_date": schedule_date,
        "available_times": schedule.available_times if schedule else [],
        "occupied_times": occupied_times,
        "created_at": schedule.created_at if schedule else datetime.utcnow(),
        "updated_at": schedule.updated_at if schedule else None,
    }
    return res


@router.post("/schedules", response_model=TechnicianScheduleResponse)
async def upsert_schedule(payload: TechnicianScheduleUpsert, db: Session = Depends(get_db)):
    # ... (same logic as batch)
    cleaned_times: List[str] = []
    # ... (skipping some lines for brevity in SEARCH but will include them in REPLACE if needed)
    # Actually, I'll just rewrite the function body for clarity
    
    # 验证与清洗时间段
    cleaned_times = []
    seen = set()
    for t in payload.available_times or []:
        if not isinstance(t, str): continue
        parts = t.split(":")
        if len(parts) != 2: continue
        hh = int(parts[0])
        label = f"{hh:02d}:00"
        if label not in seen:
            seen.add(label)
            cleaned_times.append(label)
    cleaned_times.sort()

    # 如果 service_id 为 0，表示应用到技师关联的所有服务
    service_ids = [payload.service_id]
    if payload.service_id == 0:
        tech = db.query(Technician).filter(Technician.id == payload.technician_id).first()
        if not tech:
            raise HTTPException(status_code=404, detail="技师不存在")
        service_ids = [s.id for s in tech.services]
    
    last_schedule = None
    for s_id in service_ids:
        schedule = (
            db.query(TechnicianSchedule)
            .filter(
                TechnicianSchedule.technician_id == payload.technician_id,
                TechnicianSchedule.service_id == s_id,
                TechnicianSchedule.schedule_date == payload.schedule_date,
            )
            .first()
        )
        if schedule:
            schedule.available_times = cleaned_times
        else:
            schedule = TechnicianSchedule(
                technician_id=payload.technician_id,
                service_id=s_id,
                schedule_date=payload.schedule_date,
                available_times=cleaned_times,
            )
            db.add(schedule)
        last_schedule = schedule
    
    db.commit()
    if last_schedule:
        db.refresh(last_schedule)
    return last_schedule or {
        "id": 0,
        "technician_id": payload.technician_id,
        "service_id": payload.service_id,
        "schedule_date": payload.schedule_date,
        "available_times": cleaned_times,
        "created_at": datetime.utcnow()
    }


@router.post("/schedules/batch")
async def batch_upsert_schedules(
    payload: TechnicianScheduleUpsert,
    days: int = Query(30, ge=1, le=366),
    start_date: Optional[date_type] = Query(None),
    end_date: Optional[date_type] = Query(None),
    db: Session = Depends(get_db),
):
    cleaned_times: List[str] = []
    seen = set()
    for t in payload.available_times or []:
        if not isinstance(t, str):
            raise HTTPException(status_code=400, detail="时段格式错误")
        parts = t.split(":")
        if len(parts) != 2:
            raise HTTPException(status_code=400, detail="时段格式错误")
        try:
            hh = int(parts[0])
            mm = int(parts[1])
        except ValueError:
            raise HTTPException(status_code=400, detail="时段格式错误")
        if hh < 0 or hh > 23 or mm != 0:
            raise HTTPException(status_code=400, detail="时段需按整点划分")
        label = f"{hh:02d}:00"
        if label not in seen:
            seen.add(label)
            cleaned_times.append(label)
    cleaned_times.sort()

    created = 0
    updated = 0
    if start_date is not None or end_date is not None:
        if start_date is None or end_date is None:
            raise HTTPException(status_code=400, detail="请同时提供开始与结束日期")
        if end_date < start_date:
            raise HTTPException(status_code=400, detail="结束日期不能早于开始日期")
        total_days = (end_date - start_date).days + 1
        if total_days > 366:
            raise HTTPException(status_code=400, detail="日期范围过大")
        dates = [start_date + timedelta(days=i) for i in range(total_days)]
        days = total_days
    else:
        dates = [payload.schedule_date + timedelta(days=i) for i in range(days)]

    # 🌟 优化：如果 service_id 为 0，表示应用到技师关联的所有服务
    service_ids = [payload.service_id]
    if payload.service_id == 0:
        tech = db.query(Technician).filter(Technician.id == payload.technician_id).first()
        if not tech:
            raise HTTPException(status_code=404, detail="技师不存在")
        service_ids = [s.id for s in tech.services]
    
    for d in dates:
        for s_id in service_ids:
            schedule = (
                db.query(TechnicianSchedule)
                .filter(
                    TechnicianSchedule.technician_id == payload.technician_id,
                    TechnicianSchedule.service_id == s_id,
                    TechnicianSchedule.schedule_date == d,
                )
                .first()
            )
            if schedule:
                schedule.available_times = cleaned_times
                updated += 1
            else:
                schedule = TechnicianSchedule(
                    technician_id=payload.technician_id,
                    service_id=s_id,
                    schedule_date=d,
                    available_times=cleaned_times,
                )
                db.add(schedule)
                created += 1

    db.commit()
    return {"created": created, "updated": updated, "days": days, "start_date": dates[0], "end_date": dates[-1]}


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: int, db: Session = Depends(get_db)):
    schedule = db.query(TechnicianSchedule).filter(TechnicianSchedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="排班不存在")
    db.delete(schedule)
    db.commit()
    return {"message": "已删除"}

# --- 营销号管理 (CRUD) ---

@router.get("/marketing-sources", response_model=List[MarketingSourceResponse])
async def list_marketing_sources(db: Session = Depends(get_db)):
    """获取所有营销号列表"""
    return db.query(MarketingSource).all()

@router.post("/marketing-sources", response_model=MarketingSourceResponse)
async def create_marketing_source(payload: MarketingSourceCreate, db: Session = Depends(get_db)):
    """新增营销号"""
    db_source = MarketingSource(**payload.dict())
    db.add(db_source)
    try:
        db.commit()
        db.refresh(db_source)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="营销号名称可能已存在")
    return db_source

@router.put("/marketing-sources/{source_id}", response_model=MarketingSourceResponse)
async def update_marketing_source(source_id: int, payload: MarketingSourceUpdate, db: Session = Depends(get_db)):
    """修改营销号"""
    db_source = db.query(MarketingSource).filter(MarketingSource.id == source_id).first()
    if not db_source:
        raise HTTPException(status_code=404, detail="营销号不存在")
    
    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_source, key, value)
    
    try:
        db.commit()
        db.refresh(db_source)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="更新失败")
    return db_source

@router.delete("/marketing-sources/{source_id}")
async def delete_marketing_source(source_id: int, db: Session = Depends(get_db)):
    """删除营销号"""
    db_source = db.query(MarketingSource).filter(MarketingSource.id == source_id).first()
    if not db_source:
        raise HTTPException(status_code=404, detail="营销号不存在")
    
    db.delete(db_source)
    db.commit()
    return {"message": "删除成功"}

# --- 轮播图管理 (CRUD) ---

@router.get("/carousels", response_model=List[CarouselResponse])
async def list_carousels(db: Session = Depends(get_db)):
    """获取所有轮播图列表"""
    return db.query(Carousel).order_by(Carousel.sort_order.asc(), Carousel.id.desc()).all()

@router.post("/carousels", response_model=CarouselResponse)
async def create_carousel(payload: CarouselCreate, db: Session = Depends(get_db)):
    """新增轮播图"""
    db_carousel = Carousel(**payload.dict())
    db.add(db_carousel)
    db.commit()
    db.refresh(db_carousel)
    return db_carousel

@router.put("/carousels/{carousel_id}", response_model=CarouselResponse)
async def update_carousel(carousel_id: int, payload: CarouselUpdate, db: Session = Depends(get_db)):
    """修改轮播图"""
    db_carousel = db.query(Carousel).filter(Carousel.id == carousel_id).first()
    if not db_carousel:
        raise HTTPException(status_code=404, detail="轮播图不存在")
    
    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_carousel, key, value)
    
    db.commit()
    db.refresh(db_carousel)
    return db_carousel

@router.delete("/carousels/{carousel_id}")
async def delete_carousel(carousel_id: int, db: Session = Depends(get_db)):
    """删除轮播图"""
    db_carousel = db.query(Carousel).filter(Carousel.id == carousel_id).first()
    if not db_carousel:
        raise HTTPException(status_code=404, detail="轮播图不存在")
    
    db.delete(db_carousel)
    db.commit()
    return {"message": "删除成功"}

# --- 门店信息管理 ---

@router.get("/shop-info", response_model=ShopInfoResponse)
async def get_shop_info(db: Session = Depends(get_db)):
    """获取门店信息"""
    shop_info = db.query(ShopInfo).first()
    if not shop_info:
        # 如果不存在，返回默认值
        return {
            "id": 0,
            "name": "维乐会所",
            "address": "请输入地址",
            "phone": "请输入电话",
            "hours": "11:00 - 04:00 (次日)",
            "description": "欢迎光临维乐会所",
            "latitude": 0,
            "longitude": 0,
            "updated_at": datetime.utcnow()
        }
    return shop_info

@router.put("/shop-info", response_model=ShopInfoResponse)
async def update_shop_info(payload: ShopInfoUpdate, db: Session = Depends(get_db)):
    """更新门店信息"""
    shop_info = db.query(ShopInfo).first()
    if not shop_info:
        shop_info = ShopInfo(**payload.dict())
        db.add(shop_info)
    else:
        update_data = payload.dict()
        for key, value in update_data.items():
            setattr(shop_info, key, value)
    
    db.commit()
    db.refresh(shop_info)
    return shop_info

# --- 预约管理 (占位) ---
@router.get("/bookings", response_model=PageResponse[BookingResponse])
async def get_bookings(
    status: Optional[str] = None,
    phone: Optional[str] = Query(None, description="按手机号模糊查询"),
    marketing_source_id: Optional[int] = Query(None, description="按营销号过滤"),
    page: int = Query(1, ge=1, description="当前页码"),
    size: int = Query(10, ge=1, le=100, description="每页数量(最多100条)"),
    db: Session = Depends(get_db)
):
    """获取预约单记录 (带分页)"""
    query = db.query(Booking)
    
    if status:
        query = query.filter(Booking.status == status)
    
    if phone:
        query = query.filter(Booking.customer_phone.like(f"%{phone}%"))
    
    if marketing_source_id is not None:
        query = query.filter(Booking.marketing_source_id == marketing_source_id)
        
    # 1. 查询符合条件的数据总数 (前端展示分页器必须用到)
    total = query.count()
    
    # 2. 计算分页偏移量 (offset)
    offset = (page - 1) * size
    
    # 3. 排序，并切片获取当前页的数据
    bookings = query.order_by(Booking.created_at.desc()).offset(offset).limit(size).all()
    
    # 返回符合 PageResponse 结构的数据
    return {
        "total": total,
        "page": page,
        "size": size,
        "data": bookings
    }

 
@router.put("/bookings/{booking_id}/status")
async def update_booking_status(
    booking_id: int, 
    status_in: BookingStatusUpdate, 
    db: Session = Depends(get_db)
):
    """更新预约单状态"""
    db_booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not db_booking:
        raise HTTPException(status_code=404, detail="订单不存在")
    
    db_booking.status = status_in.status
    
    # 🌟 小细节：如果是取消订单，顺手记录取消时间
    if status_in.status == 'cancelled':
        db_booking.cancelled_at = func.now()
        
    db.commit()
    return {"message": f"预约单状态已更新为 {status_in.status}"}


@router.put("/bookings/{booking_id}", response_model=BookingResponse)
async def update_booking_details(
    booking_id: int, 
    edit_in: BookingEditUpdate, 
    db: Session = Depends(get_db)
):
    """修改订单信息 (预约日期、时段、备注)"""
    db_booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not db_booking:
        raise HTTPException(status_code=404, detail="订单不存在")
    
    # 更新字段
    db_booking.booking_date = edit_in.booking_date
    db_booking.booking_times = edit_in.booking_times # SQLAlchemy 会自动把 Python List 转为 JSON 存入库中
    db_booking.note = edit_in.note
    
    db.commit()
    db.refresh(db_booking)
    
    return db_booking
