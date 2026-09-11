# ---- Build stage ----
FROM node:20-alpine AS builder
WORKDIR /app
COPY FE/package*.json ./
RUN npm ci
COPY FE/ ./
RUN npm run build

# ---- Runtime stage ----
FROM nginx:1.27-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY FE/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
