from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

# 数据库连接配置 (根据您的 MySQL 实际情况修改)
# 格式: mysql+pymysql://用户名:密码@主机名:端口号/数据库名
DEFAULT_DATABASE_URL = "mysql+pymysql://weile:weileA12345dfbshdn@10.44.110.120:3306/massage_booking_db"
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# 获取数据库连接的依赖项
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
