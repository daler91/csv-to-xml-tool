FROM node:20-alpine AS deps
WORKDIR /app
COPY apps/web/package*.json ./
# ci, not install: the image must build from the lockfile CI tested, not
# re-resolve ranges at build time.
RUN npm ci --ignore-scripts

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web/ .
ENV DATABASE_URL="postgresql://placeholder:placeholder@placeholder:5432/placeholder"
# `npm run`, not `npx`: npx would fetch and execute an arbitrary version of
# `prisma` from the registry if the local binary were ever missing. `npm run`
# only sees node_modules/.bin, i.e. the lockfile-pinned copy installed above.
RUN npm run generate
RUN npm run build

FROM node:20-alpine
# su-exec is how scripts/entrypoint.sh drops from root to `node`.
RUN apk add --no-cache su-exec
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/node_modules/.prisma ./node_modules/.prisma
COPY --from=builder /app/node_modules/@prisma/client ./node_modules/@prisma/client
COPY --from=builder /app/scripts ./scripts

# The app runs as the unprivileged user the node images already provide, and
# DATA_DIR holds uploads and generated XML, so it has to be writable by that
# user. This chown covers a fresh Docker named volume, which inherits the image
# directory's ownership on first mount -- but not a volume mounted root-owned at
# runtime, which is what Railway always does. So there is deliberately no `USER`
# here: the container starts as root, and the entrypoint re-owns DATA_DIR and
# then drops to `node` before the CMD runs.
ENV DATA_DIR=/data
RUN mkdir -p /data && chown -R node:node /app /data

# The entrypoint runs as root, so it must not live under /app, which `node` owns:
# a compromised app could rewrite it and have root run the result at the next
# container start. COPY leaves this copy root-owned.
COPY apps/web/scripts/entrypoint.sh /usr/local/bin/web-entrypoint.sh

EXPOSE 3000
ENTRYPOINT ["/bin/sh", "/usr/local/bin/web-entrypoint.sh"]
# `&&`, not `;`: a failed migration must stop the container from serving. Paired
# with the non-zero exit code in scripts/migrate.js -- either alone leaves the
# app booting against a half-migrated database.
CMD ["sh", "-c", "node scripts/migrate.js && node server.js"]
