FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -m appuser
COPY . .
RUN sh scripts/gen_proto.sh
RUN mkdir -p /app/uploads && chown -R appuser:appuser /app
USER appuser
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
