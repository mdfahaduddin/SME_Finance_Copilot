# Builds the React app and serves it with Caddy, which also terminates HTTPS
# and reverse-proxies /api to the backend (see Caddyfile).
FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Production builds never show the demo-account buttons.
ENV VITE_DEMO_MODE=false
RUN npm run build

FROM caddy:2.10-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/dist /srv
