# HoneyBadge Frontend — Production Build
# Build context: project root (../../ from deploy/docker/)

# Stage 1: Build Vue 3 + Vite app
FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ .
ARG VITE_AUTH_URL=/auth
ARG VITE_MATRIX_HOMESERVER=
RUN npm run build

# Stage 2: Serve with nginx
FROM nginx:1.25-alpine
COPY --from=build /app/dist /usr/share/nginx/html

RUN cat > /etc/nginx/conf.d/default.conf << 'NGINX'
server {
    listen 3000;
    root /usr/share/nginx/html;
    index index.html;

    # SPA fallback — all routes handled by Vue Router
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Health check
    location /healthz {
        return 200 'ok';
        add_header Content-Type text/plain;
    }
}
NGINX
# Note: /api and /auth routing is handled by k3s Traefik Ingress,
# not by nginx inside the container. The Ingress routes:
#   / → frontend:3000
#   /api → honeybadge-server:8090
#   /login, /auth → honeybadge-auth:8091

EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
