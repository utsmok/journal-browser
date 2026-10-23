FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# next build bakes rewrites into routes-manifest.json, so the proxy
# target must be set at build time (compose default: backend service).
ARG API_PROXY_URL=http://backend:8000
ENV API_PROXY_URL=$API_PROXY_URL
# Citation links always point at the public hostname, never the request origin.
ARG NEXT_PUBLIC_SITE_URL=https://journalbrowser.samuelmok.cc
ENV NEXT_PUBLIC_SITE_URL=$NEXT_PUBLIC_SITE_URL
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
# Production node_modules only; the deps stage keeps devDependencies for the build.
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY --from=build --chown=node:node /app/.next ./.next
COPY --from=build /app/next.config.mjs ./
# uid 1000 `node` ships with the base image; the app never writes to /app at runtime.
USER node
EXPOSE 3000
CMD ["npm", "run", "start"]
