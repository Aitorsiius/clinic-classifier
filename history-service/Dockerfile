FROM python:3.10-slim

WORKDIR /app

# Instalar curl para healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements e instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir --only-binary :all: -r requirements.txt

# Copiar código del servicio
COPY main.py .

# Exponer puerto
EXPOSE 8007

# Comando para ejecutar el servicio
CMD ["python", "main.py"]
