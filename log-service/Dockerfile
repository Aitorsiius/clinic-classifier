FROM python:3.10-slim

WORKDIR /app

# Instalar curl para healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements y instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir --only-binary :all: -r requirements.txt

# Copiar el código de la aplicación
COPY main.py .

# Exponer puerto
EXPOSE 8006

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=5 --start-period=60s \
  CMD curl -f http://localhost:8006/health || exit 1

# Comando para iniciar la aplicación
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8006"]
