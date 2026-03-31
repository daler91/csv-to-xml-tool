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

# Migration runner - has full node_modules for prisma CLI
FROM node:20-alpine AS migrator
WORKDIR /app
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/prisma ./prisma

# Final production image
FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=migrator /app/node_modules ./migrate_modules
COPY --from=migrator /app/prisma ./prisma
EXPOSE 3000
CMD ["sh", "-c", "cd /app && NODE_PATH=/app/migrate_modules node migrate_modules/prisma/build/index.js db push --skip-generate --schema=./prisma/schema.prisma 2>&1 || echo 'Prisma db push failed - check DATABASE_URL'; node server.js"]
