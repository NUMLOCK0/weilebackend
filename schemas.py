from pydantic import BaseModel, Field
from typing import Optional, List, TypeVar, Generic
from decimal import Decimal
from datetime import datetime, date

# --- 服务项目 Schema ---
class ServiceBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    price: Decimal = Field(..., ge=0)
    original_price: Optional[Decimal] = Field(None, ge=0)
    duration: int = Field(..., gt=0)
    image_url: Optional[str] = None
    is_hot: bool = False
    is_active: bool = True
    sort_order: int = 0

class ServiceCreate(ServiceBase):
    pass

class ServiceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[Decimal] = None
    original_price: Optional[Decimal] = None
    duration: Optional[int] = None
    image_url: Optional[str] = None
    is_hot: Optional[bool] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None

class ServiceResponse(ServiceBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

# --- 技师 Schema ---
class TechnicianBase(BaseModel):
    name: str = Field(..., max_length=50)
    title: Optional[str] = None
    avatar_url: Optional[str] = None
    rating: Decimal = Field(5.0, ge=0, le=5.0)
    color: Optional[str] = None
    is_active: bool = True
    sort_order: int = 0

class TechnicianCreate(TechnicianBase):
    service_ids: List[int] = [] # 创建时关联的服务ID列表

class TechnicianUpdate(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    avatar_url: Optional[str] = None
    rating: Optional[Decimal] = None
    color: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None
    service_ids: Optional[List[int]] = None

class TechnicianResponse(TechnicianBase):
    id: int
    created_at: datetime
    services: List[ServiceResponse] = [] # 返回关联的服务详情

    class Config:
        from_attributes = True

# --- 登录相关 Schema ---
class LoginRequest(BaseModel):
    username: str
    password: str
    captcha_id: str
    captcha_code: str

class CaptchaResponse(BaseModel):
    captcha_id: str
    captcha_image: str # Base64 图片数据

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


# --- 响应模型 (用于 GET /bookings) ---
class BookingResponse(BaseModel):
    id: int
    user_openid: str
    service_id: int
    technician_id: int
    marketing_source_id: Optional[int] = None
    service_name: Optional[str] = None      # 🌟 后端 Join 返回
    technician_name: Optional[str] = None   # 🌟 后端 Join 返回
    marketing_source_name: Optional[str] = None # 🌟 后端 Join 返回
    booking_date: date
    booking_times: List[str]  # 🌟 FastAPI 会自动把后端的 JSON 转换成 List 返回给前端
    total_price: Decimal
    customer_name: str
    customer_phone: str
    note: Optional[str] = None
    status: str
    created_at: datetime
    cancelled_at: Optional[datetime] = None

    class Config:
        from_attributes = True  # 如果你用的是 Pydantic v1, 请改为 orm_mode = True

# --- 更新状态请求模型 (用于 PUT /bookings/{id}/status) ---
class BookingStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(pending|completed|cancelled)$")

# --- 编辑订单请求模型 (用于 PUT /bookings/{id}) ---
class BookingEditUpdate(BaseModel):
    booking_date: date
    booking_times: List[str]  # 前端传过来的 ["11:00", "11:30"]
    note: Optional[str] = None


class TechnicianScheduleUpsert(BaseModel):
    technician_id: int
    service_id: int
    schedule_date: date
    available_times: List[str] = Field(default_factory=list)


class TechnicianScheduleResponse(BaseModel):
    id: int
    technician_id: int
    service_id: int
    schedule_date: date
    available_times: List[str]
    occupied_times: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AvailabilityResponse(BaseModel):
    technician_id: int
    service_id: int
    schedule_date: date
    available_times: List[str]
    booked_times: List[str]


class BookingCreateRequest(BaseModel):
    user_openid: Optional[str] = None
    service_id: int
    technician_id: int
    marketing_source_id: Optional[int] = None
    booking_date: date
    booking_times: List[str] = Field(default_factory=list)
    customer_name: str
    customer_phone: str
    note: Optional[str] = None


# --- 营销号相关 Schema ---
class MarketingSourceBase(BaseModel):
    name: str = Field(..., max_length=100)
    contact_name: Optional[str] = Field(None, max_length=50)
    contact_phone: Optional[str] = Field(None, max_length=20)
    is_active: bool = True
    note: Optional[str] = None

class MarketingSourceCreate(MarketingSourceBase):
    pass

class MarketingSourceUpdate(BaseModel):
    name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    is_active: Optional[bool] = None
    note: Optional[str] = None

class MarketingSourceResponse(MarketingSourceBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# --- 轮播图相关 Schema ---
class CarouselBase(BaseModel):
    image_url: str = Field(..., max_length=255)
    link_url: Optional[str] = Field(None, max_length=255)
    sort_order: int = 0
    is_active: bool = True

class CarouselCreate(CarouselBase):
    pass

class CarouselUpdate(BaseModel):
    image_url: Optional[str] = None
    link_url: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None

class CarouselResponse(CarouselBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# --- 门店信息相关 Schema ---
class ShopInfoBase(BaseModel):
    name: str = Field(..., max_length=100)
    address: str = Field(..., max_length=255)
    phone: str = Field(..., max_length=20)
    hours: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    image_url: Optional[str] = Field(None, max_length=255)
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None

class ShopInfoUpdate(ShopInfoBase):
    pass

class ShopInfoResponse(ShopInfoBase):
    id: int
    updated_at: datetime

    class Config:
        from_attributes = True


T = TypeVar("T")

# 🌟 通用分页返回模型
class PageResponse(BaseModel, Generic[T]):
    total: int
    page: int
    size: int
    data: List[T]
