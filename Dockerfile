# 使用官方 Python 轻量级镜像
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 复制依赖清单并安装
# 使用清华源加速下载
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制项目代码
COPY . .

# 暴露端口（微信云托管默认建议使用 80 端口）
EXPOSE 80

# 启动命令
# 注意：必须监听 0.0.0.0，端口需与 EXPOSE 一致
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]