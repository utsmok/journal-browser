FROM node:26.3.0-alpine3.22 AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:26.3.0-alpine3.22 AS build
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

FROM node:26.3.0-alpine3.22 AS runner
WORKDIR /app
ENV NODE_ENV=production
# Production node_modules only; the deps stage keeps devDependencies for the build.
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY --from=build --chown=node:node /app/.next ./.next
COPY --from=build /app/next.config.mjs ./
# Brand marks (logo.tsx references /ojb-wordmark.svg, /obj-monogram.svg);
# `next start` serves public/ from disk, so the runner stage needs the copy.
COPY --from=build /app/public ./public
# uid 1000 `node` ships with the base image; the app never writes to /app at runtime.
USER node
EXPOSE 3000
CMD ["npm", "run", "start"]
