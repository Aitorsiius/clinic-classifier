FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements y instalar
COPY requirements.txt .
RUN pip install --no-cache-dir --only-binary :all: -r requirements.txt

# Copiar aplicación y credenciales
COPY main.py .
RUN mkdir -p /app/credentials

# Exponer puerto
EXPOSE 8003

# Comando para ejecutar la aplicación
CMD ["python", "main.py"]
