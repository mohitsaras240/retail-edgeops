FROM python:3.12-slim
RUN useradd --system --uid 10001 pos && mkdir /data && chown pos /data
COPY app.py /app/app.py
USER pos
ENV DB_PATH=/data/pos.db PORT=8080
EXPOSE 8080
HEALTHCHECK --interval=3s --timeout=2s --start-period=3s --retries=2 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=1).status == 200 else 1)"
CMD ["python", "/app/app.py"]
