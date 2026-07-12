FROM python:3.11-alpine

# build context 为项目根目录
WORKDIR /app

# 安装系统依赖 (Alpine 需要这些来编译 Python 包) — 使用腾讯云 apk 源加速
RUN sed -i 's|dl-cdn.alpinelinux.org|mirrors.cloud.tencent.com|g' /etc/apk/repositories && \
    apk add --no-cache gcc musl-dev libffi-dev

# 安装Python依赖 — 使用腾讯云 pypi 源加速
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.cloud.tencent.com/pypi/simple/

# 复制后端源码
COPY backend/ ./

# 复制前端静态文件到 /app/../frontend (即 /frontend)，
# main.py 用 Path(__file__).parent.parent / "frontend" 定位
COPY frontend /frontend

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
