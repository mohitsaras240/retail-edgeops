FROM python:3.12-slim
WORKDIR /app
COPY app.py .
ENV PORT=8080
ENV STORE_ID=store-001
ENV DB_PATH=/data/pos.db
ENV CENTRAL_URL=http://autopilot-backend:8000/central/ingest
ENV SYNC_INTERVAL_S=5
ENV ENABLE_FAULT_ENDPOINTS=0
EXPOSE 8080
CMD ["python", "app.py"]
