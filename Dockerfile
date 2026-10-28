# Build from the hciproj folder:  docker build -t cadence .
FROM python:3.12-slim
WORKDIR /app
COPY cadence/requirements.txt cadence/requirements.txt
RUN pip install --no-cache-dir -r cadence/requirements.txt
COPY cadence cadence
WORKDIR /app/cadence
ENV CADENCE_DATA=/data CADENCE_MATERIAL=/data/material CADENCE_MULTI=1 PORT=7860
# ponytail: SQLite lives in /data; mount a persistent disk there or progress resets on redeploy
CMD ["sh","-c","exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
