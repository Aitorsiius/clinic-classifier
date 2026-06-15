# Dockerfile para el Backend (CIE-10 Classifier)
FROM python:3.11-slim

# Establecer directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema necesarias
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    g++ \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements
COPY cie_classifier/requirements.txt .

# Instalar dependencias de Python
RUN pip install --no-cache-dir --only-binary :all: -r requirements.txt

# Copiar el código de la aplicación
COPY cie_classifier/main.py .
COPY cie_classifier/api.py .
COPY cie10_qdrant/ ./cie10_qdrant/

# Exponer puerto
EXPOSE 8000

# Comando para ejecutar la aplicación
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
