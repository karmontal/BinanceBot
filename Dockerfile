FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY binancebot/ binancebot/
COPY main.py config.yaml ./

# data/ (SQLite state) and reports/ are mounted as volumes by docker-compose.
CMD ["python", "main.py", "run"]
