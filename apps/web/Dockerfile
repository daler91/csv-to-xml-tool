FROM node:20-alpine AS deps
WORKDIR /app
COPY apps/web/package*.json ./
RUN npm install --ignore-scripts

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web/ .
ENV DATABASE_URL="postgresql://placeholder:placeholder@placeholder:5432/placeholder"
RUN npx prisma generate
RUN npm run build

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/node_modules/.prisma ./node_modules/.prisma
COPY --from=builder /app/node_modules/@prisma/client ./node_modules/@prisma/client
COPY --from=builder /app/scripts ./scripts

# Run as the unprivileged user the node images already provide. DATA_DIR holds
# uploads and generated XML, so it has to be writable by that user -- a fresh
# named volume inherits ownership from the image directory on first mount.
ENV DATA_DIR=/data
RUN mkdir -p /data && chown -R node:node /app /data
USER node

EXPOSE 3000
# `&&`, not `;`: a failed migration must stop the container from serving. Paired
# with the non-zero exit code in scripts/migrate.js -- either alone leaves the
# app booting against a half-migrated database.
CMD ["sh", "-c", "node scripts/migrate.js && node server.js"]
