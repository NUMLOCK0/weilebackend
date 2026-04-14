from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

# 数据库连接配置 (根据您的 MySQL 实际情况修改)
# 格式: mysql+pymysql://用户名:密码@主机名:端口号/数据库名

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

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
