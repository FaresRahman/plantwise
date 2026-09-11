# ---- Build stage ----
FROM python:3.12-slim AS builder
WORKDIR /app
COPY BE/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ---- Runtime stage ----
FROM python:3.12-slim
WORKDIR /app

# Create non-root user
RUN groupadd -r plantwise && useradd -r -g plantwise plantwise

COPY --from=builder /root/.local /home/plantwise/.local
ENV PATH=/home/plantwise/.local/bin:$PATH

# Copy application code
COPY BE/ /app/BE/

# Ensure storage dir exists for SOP uploads
RUN mkdir -p /app/BE/storage && chown -R plantwise:plantwise /app && chmod +x /app/BE/docker-entrypoint.sh

USER plantwise

EXPOSE 8000

ENTRYPOINT ["/app/BE/docker-entrypoint.sh"]

# Gunicorn with Uvicorn workers — production-grade ASGI
# --worker-tmp-dir /dev/shm improves perf (shared memory)
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", \
     "--bind", "0.0.0.0:8000", \
     "--worker-tmp-dir", "/dev/shm", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--timeout", "120"]
