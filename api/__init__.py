from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import date as date_type
import httpx
import json
import os

from database import get_db
from models import Service, Technician, Booking, TechnicianSchedule, MarketingSource, Carousel, ShopInfo
from schemas import (
    ServiceResponse,
    TechnicianResponse,
    AvailabilityResponse,
    BookingCreateRequest,
    BookingResponse,
    MarketingSourceResponse,
    CarouselResponse,
    ShopInfoResponse,
)
from pydantic import BaseModel
from security import get_current_client_user, create_access_token

router = APIRouter()

class ClientLoginRequest(BaseModel):
    code: Optional[str] = None
    userInfo: Optional[dict] = None

@router.post("/login", summary="客户端登录 (微信登录)")
async def client_login(
    req: ClientLoginRequest,
    x_wx_openid: Optional[str] = Header(None, alias="X-WX-OPENID")
):
    openid = x_wx_openid
    
    if not openid:
        if not req.code:
            raise HTTPException(status_code=400, detail="缺少登录凭证 code")
            
        app_id = os.getenv("WECHAT_APP_ID")
        app_secret = os.getenv("WECHAT_APP_SECRET")
        
        if app_id and app_secret:
            url = f"https://api.weixin.qq.com/sns/jscode2session?appid={app_id}&secret={app_secret}&js_code={req.code}&grant_type=authorization_code"
            try:
                async with httpx.AsyncClient(verify=False) as client:
                    response = await client.get(url, timeout=10.0)
                    if response.status_code == 200:
                        data = response.json()
                        if "openid" in data:
                            openid = data["openid"]
                        else:
                            raise HTTPException(status_code=400, detail=f"微信登录失败: {data.get('errmsg')}")
                    else:
                        raise HTTPException(status_code=500, detail=f"请求微信接口 HTTP 错误: {response.status_code}")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"请求微信接口失败: {str(e)}")
        else:
            # 本地开发环境，如果没有配置 appid 和 secret，使用 mock 的 openid
            openid = f"mock_openid_{req.code}"
            
    if not openid:
        raise HTTPException(status_code=400, detail="无法获取 openid")

    access_token = create_access_token(data={"sub": openid})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "openid": openid
    }

@router.get("/services", response_model=List[ServiceResponse])
async def get_services(db: Session = Depends(get_db)):
    return db.query(Service).filter(Service.is_active == True).all()


@router.get("/carousels", response_model=List[CarouselResponse])
async def get_carousels(db: Session = Depends(get_db)):
    return db.query(Carousel).filter(Carousel.is_active == True).order_by(Carousel.sort_order.asc()).all()


@router.get("/shop-info", response_model=Optional[ShopInfoResponse])
async def get_shop_info(db: Session = Depends(get_db)):
    return db.query(ShopInfo).first()


@router.get("/marketing-sources", response_model=List[MarketingSourceResponse])
async def get_marketing_sources(db: Session = Depends(get_db)):
    return db.query(MarketingSource).filter(MarketingSource.is_active == True).all()


@router.get("/technicians", response_model=List[TechnicianResponse])
async def get_technicians(service_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(Technician).filter(Technician.is_active == True)
    if service_id is not None:
        query = query.filter(Technician.services.any(Service.id == service_id))
    return query.all()


@router.get("/availability", response_model=AvailabilityResponse)
async def get_availability(
    technician_id: int = Query(..., ge=1),
    service_id: int = Query(..., ge=1),
    schedule_date: date_type = Query(...),
    db: Session = Depends(get_db),
):
    schedule = (
        db.query(TechnicianSchedule)
        .filter(
            TechnicianSchedule.technician_id == technician_id,
            TechnicianSchedule.service_id == service_id,
            TechnicianSchedule.schedule_date == schedule_date,
        )
        .first()
    )
    bookings = (
        db.query(Booking)
        .filter(
            Booking.technician_id == technician_id,
            Booking.booking_date == schedule_date,
            Booking.status != "cancelled",
        )
        .all()
    )
    booked_times: List[str] = []
    for b in bookings:
        if isinstance(b.booking_times, list):
            booked_times.extend([t for t in b.booking_times if isinstance(t, str)])
    booked_times = sorted(set(booked_times))

    available_times = schedule.available_times if schedule and isinstance(schedule.available_times, list) else []
    available_times = [t for t in available_times if isinstance(t, str)]

    return {
        "technician_id": technician_id,
        "service_id": service_id,
        "schedule_date": schedule_date,
        "available_times": available_times,
        "booked_times": booked_times,
    }


@router.post("/bookings", response_model=BookingResponse)
async def create_booking(
    payload: BookingCreateRequest, 
    db: Session = Depends(get_db),
    current_openid: str = Depends(get_current_client_user)
):
    service = db.query(Service).filter(Service.id == payload.service_id, Service.is_active == True).first()
    if not service:
        raise HTTPException(status_code=404, detail="服务项目不存在")

    technician = db.query(Technician).filter(Technician.id == payload.technician_id, Technician.is_active == True).first()
    if not technician:
        raise HTTPException(status_code=404, detail="技师不存在")

    supports_service = any(s.id == service.id for s in (technician.services or []))
    if not supports_service:
        raise HTTPException(status_code=400, detail="该技师不支持所选服务项目")

    requested_times = payload.booking_times or []
    requested_times = [t for t in requested_times if isinstance(t, str)]

    if requested_times:
        schedule = (
            db.query(TechnicianSchedule)
            .filter(
                TechnicianSchedule.technician_id == payload.technician_id,
                TechnicianSchedule.service_id == payload.service_id,
                TechnicianSchedule.schedule_date == payload.booking_date,
            )
            .first()
        )
        available_times = schedule.available_times if schedule and isinstance(schedule.available_times, list) else []
        available_times = {t for t in available_times if isinstance(t, str)}
        if not available_times:
            raise HTTPException(status_code=400, detail="该日期暂无可预约时段")

        for t in requested_times:
            if t not in available_times:
                raise HTTPException(status_code=400, detail=f"时段不可预约: {t}")

        conflicting = (
            db.query(Booking)
            .filter(
                Booking.technician_id == payload.technician_id,
                Booking.booking_date == payload.booking_date,
                Booking.status != "cancelled",
            )
            .all()
        )
        booked = set()
        for b in conflicting:
            if isinstance(b.booking_times, list):
                booked.update([t for t in b.booking_times if isinstance(t, str)])
        overlap = sorted(set(requested_times) & booked)
        if overlap:
            raise HTTPException(status_code=409, detail=f"时段已被预约: {', '.join(overlap)}")

    user_openid = current_openid

    booking = Booking(
        user_openid=user_openid,
        service_id=payload.service_id,
        technician_id=payload.technician_id,
        marketing_source_id=payload.marketing_source_id,
        booking_date=payload.booking_date,
        booking_times=requested_times,
        total_price=service.price * max(len(requested_times), 1),
        customer_name=payload.customer_name,
        customer_phone=payload.customer_phone,
        note=payload.note,
        status="pending",
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


@router.get("/bookings", response_model=List[BookingResponse])
async def list_user_bookings(
    db: Session = Depends(get_db),
    current_openid: str = Depends(get_current_client_user)
):
    bookings = (
        db.query(Booking)
        .filter(Booking.user_openid == current_openid)
        .order_by(Booking.created_at.desc())
        .all()
    )
    return bookings


@router.put("/bookings/{booking_id}/cancel")
async def cancel_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_openid: str = Depends(get_current_client_user)
):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="订单不存在")
    if booking.user_openid != current_openid:
        raise HTTPException(status_code=403, detail="无权限取消该订单")
    if booking.status == "cancelled":
        return {"message": "已取消"}
    booking.status = "cancelled"
    booking.cancelled_at = func.now()
    db.commit()
    return {"message": "已取消"}


@router.get("/test")
async def test_api():
    return {"message": "Client API router works"}
