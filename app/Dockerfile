# Dockerfile multi-stage para la aplicación frontend
# Etapa 1: Build - Usando la imagen de Microsoft para evadir el error de certificado de Docker Hub
FROM mcr.microsoft.com/devcontainers/javascript-node:20 AS builder

WORKDIR /app

# Argumento para la URL del API Gateway
ARG API_GATEWAY_URL=http://localhost:3000

# Copiar package files
COPY package.json package-lock.json* ./

# Instalar dependencias
RUN npm install

# Copiar el resto del código
COPY . .

# Crear archivo .env con la URL del API Gateway
RUN echo "API_GATEWAY_URL=${API_GATEWAY_URL}" > .env

# Construir la aplicación
RUN npm run build

# Etapa 2: Production
FROM nginx:alpine

# Copiar los archivos compilados desde el builder
COPY --from=builder /app/dist /usr/share/nginx/html

# Copiar configuración personalizada de nginx
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Exponer puerto
EXPOSE 80

# Comando por defecto de nginx
CMD ["nginx", "-g", "daemon off;"]
