# ==========================================
# SafeGuard-AI (安卫智脑) — 多阶段 Docker 构建
# ==========================================
# 构建:  docker build -t safeguard-api:latest .
# 运行:  docker run -p 8000:8000 --env-file .env safeguard-api:latest
# ==========================================

# ====================
# Stage 1: 构建阶段
# ====================
FROM python:3.11-slim AS builder

# 安装编译依赖（cryptography、opencv 等需要 C 编译器）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# 创建虚拟环境（确保运行阶段路径一致）
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 安装 Python 依赖（利用 Docker 层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# ====================
# Stage 2: 运行阶段
# ====================
FROM python:3.11-slim AS runtime

# 安装运行时系统库
#   libgomp1 — OpenMP 运行时（opencv-python-headless 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 从构建阶段复制虚拟环境
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 设置工作目录
WORKDIR /app

# 复制应用代码（排除 .dockerignore 中列出的文件）
# 注意：mock_data/ 已被 .dockerignore 排除（生产环境使用真实数据库）
COPY app/ app/

# 暴露 FastAPI 默认端口
EXPOSE 8000

# 健康检查（每 30s 探测一次）
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()" || exit 1

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
