from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Query
import os
import shutil
import uuid
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

# --- 文件上传接口 ---

@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """上传文件到服务器并返回可访问 URL"""
    # 确保存储目录存在
    upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
        
    # 生成唯一文件名
    ext = os.path.splitext(file.filename)[1]
    filename = f"{uuid.uuid4()}{ext}"
    file_path = os.path.join(upload_dir, filename)
    
    # 保存文件
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # 返回相对路径 (前端通过 /uploads/xxx 访问)
    return {"url": f"/uploads/{filename}"}

# --- 服务管理 (CRUD) ---

@router.get("/services", response_model=List[ServiceResponse])
async def get_services(db: Session = Depends(get_db)):
    """获取所有服务项目"""
    services = db.query(Service).all()
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
    return db.query(Technician).all()

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
    start_date: Optional[date_type] = None,
    end_date: Optional[date_type] = None,
    db: Session = Depends(get_db),
):
    query = db.query(TechnicianSchedule)
    if technician_id is not None:
        query = query.filter(TechnicianSchedule.technician_id == technician_id)
    if start_date is not None:
        query = query.filter(TechnicianSchedule.schedule_date >= start_date)
    if end_date is not None:
        query = query.filter(TechnicianSchedule.schedule_date <= end_date)
    return query.order_by(TechnicianSchedule.schedule_date.desc(), TechnicianSchedule.id.desc()).all()


@router.get("/schedules/{technician_id}/{schedule_date}", response_model=TechnicianScheduleResponse)
async def get_schedule(
    technician_id: int,
    schedule_date: date_type,
    db: Session = Depends(get_db),
):
    schedule = (
        db.query(TechnicianSchedule)
        .filter(
            TechnicianSchedule.technician_id == technician_id,
            TechnicianSchedule.schedule_date == schedule_date,
        )
        .first()
    )
    if not schedule:
        return {
            "id": 0,
            "technician_id": technician_id,
            "schedule_date": schedule_date,
            "available_times": [],
            "created_at": datetime.utcnow(),
            "updated_at": None,
        }
    return schedule


@router.post("/schedules", response_model=TechnicianScheduleResponse)
async def upsert_schedule(payload: TechnicianScheduleUpsert, db: Session = Depends(get_db)):
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

    schedule = (
        db.query(TechnicianSchedule)
        .filter(
            TechnicianSchedule.technician_id == payload.technician_id,
            TechnicianSchedule.schedule_date == payload.schedule_date,
        )
        .first()
    )
    if schedule:
        schedule.available_times = cleaned_times
    else:
        schedule = TechnicianSchedule(
            technician_id=payload.technician_id,
            schedule_date=payload.schedule_date,
            available_times=cleaned_times,
        )
        db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


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

    for d in dates:
        schedule = (
            db.query(TechnicianSchedule)
            .filter(
                TechnicianSchedule.technician_id == payload.technician_id,
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
            "hours": "11:00 - 05:00",
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
    page: int = Query(1, ge=1, description="当前页码"),
    size: int = Query(10, ge=1, le=100, description="每页数量(最多100条)"),
    db: Session = Depends(get_db)
):
    """获取预约单记录 (带分页)"""
    query = db.query(Booking)
    
    if status:
        query = query.filter(Booking.status == status)
        
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
