FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci || npm install

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# next build bakes rewrites into routes-manifest.json, so the proxy
# target must be set at build time (compose default: backend service).
ARG API_PROXY_URL=http://backend:8000
ENV API_PROXY_URL=$API_PROXY_URL
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app ./
EXPOSE 3000
CMD ["npm", "run", "start"]
