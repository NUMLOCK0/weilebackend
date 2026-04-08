from sqlalchemy import Column, Integer, String, DECIMAL, Boolean, Text, TIMESTAMP, func, ForeignKey, Date, JSON, Numeric, Enum, UniqueConstraint
from sqlalchemy.orm import relationship
from database import Base

class Service(Base):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    price = Column(DECIMAL(10, 2), nullable=False)
    original_price = Column(DECIMAL(10, 2))
    duration = Column(Integer, nullable=False)
    image_url = Column(String(255))
    is_hot = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())

    # 关联技师 (多对多)
    technicians = relationship("Technician", secondary="technician_services", back_populates="services")

class Technician(Base):
    __tablename__ = "technicians"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(50), nullable=False)
    title = Column(String(50))
    avatar_url = Column(String(255))
    rating = Column(DECIMAL(2, 1), default=5.0)
    color = Column(String(10))
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())

    # 关联服务 (多对多)
    services = relationship("Service", secondary="technician_services", back_populates="technicians")

class TechnicianService(Base):
    __tablename__ = "technician_services"

    technician_id = Column(Integer, ForeignKey("technicians.id", ondelete="CASCADE"), primary_key=True)
    service_id = Column(Integer, ForeignKey("services.id", ondelete="CASCADE"), primary_key=True)

class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())

class Captcha(Base):
    __tablename__ = "captchas"

    id = Column(String(64), primary_key=True)
    code = Column(String(10), nullable=False)
    expire_at = Column(TIMESTAMP, nullable=False)
    is_used = Column(Boolean, default=False)
    created_at = Column(TIMESTAMP, server_default=func.now())

class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_openid = Column(String(64), nullable=False, comment="关联用户")
    service_id = Column(Integer, nullable=False, comment="关联服务")
    technician_id = Column(Integer, nullable=False, comment="关联技师")
    marketing_source_id = Column(Integer, nullable=True, comment="关联营销号")
    booking_date = Column(Date, nullable=False, comment="预约日期")
    
    # 🌟 核心：使用 JSON 类型处理 ["11:00", "12:00"] 这种数组
    booking_times = Column(JSON, nullable=False, comment="预约时间段")
    
    total_price = Column(Numeric(10, 2), nullable=False, comment="总价")
    customer_name = Column(String(50), nullable=False, comment="预约人姓名")
    customer_phone = Column(String(20), nullable=False, comment="预约人手机")
    note = Column(Text, nullable=True, comment="备注")
    
    # 🌟 对齐数据库的枚举状态
    status = Column(Enum('pending', 'completed', 'cancelled', name='booking_status'), default='pending')
    
    created_at = Column(TIMESTAMP, server_default=func.now())
    cancelled_at = Column(TIMESTAMP, nullable=True)

class MarketingSource(Base):
    __tablename__ = "marketing_sources"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    contact_name = Column(String(50))
    contact_phone = Column(String(20))
    is_active = Column(Boolean, default=True)
    note = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())

class Carousel(Base):
    __tablename__ = "carousels"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    image_url = Column(String(255), nullable=False)
    link_url = Column(String(255))
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())

class ShopInfo(Base):
    __tablename__ = "shop_info"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    address = Column(String(255), nullable=False)
    phone = Column(String(20), nullable=False)
    hours = Column(String(100)) # 营业时间
    description = Column(Text) # 门店描述
    image_url = Column(String(255)) # 门店图片
    latitude = Column(DECIMAL(10, 6)) # 纬度
    longitude = Column(DECIMAL(10, 6)) # 经度
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

class TechnicianSchedule(Base):
    __tablename__ = "technician_schedules"
    __table_args__ = (UniqueConstraint("technician_id", "schedule_date", name="uq_technician_date"),)

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    technician_id = Column(Integer, ForeignKey("technicians.id", ondelete="CASCADE"), nullable=False, index=True)
    schedule_date = Column(Date, nullable=False, index=True)
    available_times = Column(JSON, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
