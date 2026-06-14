# Dockerfile para el API Gateway
FROM python:3.11-slim

# Establecer directorio de trabajo
WORKDIR /app

# Instalar curl para healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements
COPY requirements.txt .

# Instalar dependencias de Python
RUN pip install --no-cache-dir --only-binary :all: -r requirements.txt

# Copiar el código de la aplicación
COPY main.py .

# Exponer puerto
EXPOSE 3000

# Variable de entorno para el backend
ENV BACKEND_URL=http://backend:8000

# Comando para ejecutar la aplicación
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3000"]
