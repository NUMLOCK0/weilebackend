from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher
from datetime import datetime, timedelta, timezone
from typing import Optional
import os
import jwt # 需要安装 PyJWT
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from database import get_db

# 🌟 密码加密配置：使用 pwdlib 和 BcryptHasher
# 实例化 PasswordHash 并传入你希望支持的哈希器元组
password_hash = PasswordHash((BcryptHasher(),))

# JWT 配置 (从环境变量读取，提供默认值仅供本地测试)
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "34324324324asdsasdsaadasd")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 24小时

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return password_hash.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """生成密码哈希"""
    return password_hash.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建 JWT Token"""
    to_encode = data.copy()
    
    # 保持使用推荐的 timezone-aware 时间戳
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
        
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_access_token(token: str) -> dict | None:
    """
    验证并解析 JWT Token
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        print("Token 已过期")
        return None
    except jwt.InvalidTokenError:
        print("Token 无效")
        return None

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/admin/login")

def get_current_admin_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    from models import AdminUser
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未验证的凭据或已过期",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = verify_access_token(token)
    if payload is None:
        raise credentials_exception
    
    username: str = payload.get("sub")
    if username is None:
        raise credentials_exception
        
    admin = db.query(AdminUser).filter(AdminUser.username == username).first()
    if admin is None:
        raise credentials_exception
    if not admin.is_active:
        raise HTTPException(status_code=403, detail="账户已禁用")
    return admin

client_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")

def get_current_client_user(token: str = Depends(client_oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的客户端凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = verify_access_token(token)
    if payload is None:
        raise credentials_exception
    
    openid: str = payload.get("sub")
    if openid is None:
        raise credentials_exception
    return openid


