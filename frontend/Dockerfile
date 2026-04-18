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

    # SPA fallback
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API proxy to backend
    location /api/ {
        proxy_pass http://honeybadge-server:8090;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # Auth proxy
    location /login {
        proxy_pass http://honeybadge-auth:8091;
        proxy_set_header Host $host;
    }
    location /auth/ {
        proxy_pass http://honeybadge-auth:8091;
        proxy_set_header Host $host;
    }

    # Health check
    location /healthz {
        return 200 'ok';
        add_header Content-Type text/plain;
    }
}
NGINX

EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
