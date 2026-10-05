# WakuFlow Assist - Phase 1 webhook server (stdlib only; no pip deps at runtime)
FROM python:3.11-slim

WORKDIR /app
COPY phase3 ./phase3
COPY phase5 ./phase5
COPY phase6 ./phase6
COPY phase8 ./phase8

ENV PYTHONPATH=/app
ENV PORT=8080
EXPOSE 8080

# Data dir for the SQLite store (mount a volume here to persist tickets).
RUN mkdir -p /app/data
ENV ASSIST_DB_PATH=/app/data/assist.db

CMD ["python3", "-m", "phase8.webhook_server"]
