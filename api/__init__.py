from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import date as date_type

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

router = APIRouter()


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
    schedule_date: date_type = Query(...),
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
        "schedule_date": schedule_date,
        "available_times": available_times,
        "booked_times": booked_times,
    }


@router.post("/bookings", response_model=BookingResponse)
async def create_booking(payload: BookingCreateRequest, db: Session = Depends(get_db)):
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

    user_openid = payload.user_openid or payload.customer_phone

    booking = Booking(
        user_openid=user_openid,
        service_id=payload.service_id,
        technician_id=payload.technician_id,
        marketing_source_id=payload.marketing_source_id,
        booking_date=payload.booking_date,
        booking_times=requested_times,
        total_price=service.price,
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
async def list_user_bookings(user_openid: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    bookings = (
        db.query(Booking)
        .filter(Booking.user_openid == user_openid)
        .order_by(Booking.created_at.desc())
        .all()
    )
    return bookings


@router.put("/bookings/{booking_id}/cancel")
async def cancel_booking(
    booking_id: int,
    user_openid: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="订单不存在")
    if user_openid is not None and booking.user_openid != user_openid:
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
