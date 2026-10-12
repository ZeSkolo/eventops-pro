FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 EVENTOPS_DATA_DIR=/data
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 eventops && useradd --uid 10001 --gid eventops --create-home eventops
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=eventops:eventops . .
RUN mkdir -p /data && chown eventops:eventops /data
USER eventops
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
