FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/service:/app \
    GONGMUDAM_DATA_ROOT=/var/lib/gongmudam GONGMUDAM_NO_LLM=1 GONGMUDAM_CLOUD=1
WORKDIR /app
ARG SOURCE_COMMIT=unconfigured
ARG RELEASE_ID=unconfigured
LABEL org.opencontainers.image.revision=$SOURCE_COMMIT com.gongmudam.release=$RELEASE_ID
COPY service/requirements-cloud.lock.txt /app/service/requirements-cloud.lock.txt
RUN python -m pip install --no-cache-dir -r service/requirements-cloud.lock.txt \
    && groupadd --gid 10001 gongmudam \
    && useradd --uid 10001 --gid 10001 --no-create-home gongmudam \
    && mkdir -p /var/lib/gongmudam && chown 10001:10001 /var/lib/gongmudam
COPY --chown=10001:10001 . /app
USER 10001:10001
EXPOSE 8892
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8892/health/live',timeout=3)"
CMD ["python", "-m", "uvicorn", "integration.cloud:create_app", "--factory", "--host", "0.0.0.0", "--port", "8892", "--workers", "1", "--no-access-log"]
