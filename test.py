from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher

# 1. 初始化密码哈希器
password_hash = PasswordHash((BcryptHasher(),))

# 2. 你的明文密码
plain_password = "123456"

# 3. 生成哈希值
hashed_password = password_hash.hash(plain_password)

print("=== 密码生成结果 ===")
print(f"明文密码: {plain_password}")
print(f"哈希密码: {hashed_password}")