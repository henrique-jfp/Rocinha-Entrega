# syntax=docker/dockerfile:1

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Workdir é a pasta delivery_system
WORKDIR /app

# Sistema básico
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copia requirements e instala
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código
COPY . .

# Porta do web service (Render define $PORT)
ENV PORT=8000

# Comando padrão (web). O worker do bot usará outro comando no Render.
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "${PORT}"]
