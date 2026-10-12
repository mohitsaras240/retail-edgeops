FROM python:3.12-slim
WORKDIR /app
COPY app.py .
ENV PORT=8080
ENV STORE_ID=store-001
ENV KIOSK_ID=kiosk-001
ENV DB_PATH=/data/kiosk.db
ENV ENABLE_FAULT_ENDPOINTS=0
EXPOSE 8080
CMD ["python", "app.py"]
