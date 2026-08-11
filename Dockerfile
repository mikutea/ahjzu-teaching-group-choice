FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

WORKDIR /srv/app

COPY server/requirements.txt /srv/app/server/requirements.txt
RUN pip install --no-cache-dir --requirement /srv/app/server/requirements.txt \
    && addgroup --system --gid 10001 app \
    && adduser --system --uid 10001 --ingroup app --home /nonexistent --no-create-home app

COPY server /srv/app/server
COPY web /srv/app/web
COPY assets /srv/app/assets

RUN mkdir -p /data /tmp/app \
    && chown -R app:app /data /tmp/app /srv/app

USER app:app
EXPOSE 8080

HEALTHCHECK --interval=20s --timeout=4s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3)"

CMD ["uvicorn", "server.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]

