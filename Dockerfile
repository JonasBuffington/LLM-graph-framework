# Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /code

RUN pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock* ./
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-root

COPY app ./app

# Copy and prepare the startup script
COPY start.sh .
RUN chmod +x ./start.sh

EXPOSE 8000
# Use the script as the container's command
CMD ["./start.sh"]