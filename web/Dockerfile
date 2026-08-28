# Interface web Next.js (service web/ du docker-compose).
#
# Build multi-étapes : deps -> build (output "standalone") -> runner minimal.
# Ref : node_modules/next/dist/docs/01-app/03-api-reference/05-config/01-next-config-js/output.md
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ---- Build ----
FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
# API_URL est lu par next.config.ts (rewrites) AU BUILD, puis sérialisé dans server.js.
# En dev local (npm run dev), le défaut "http://localhost:8000" s'applique.
# En Docker, la valeur est fournie par docker-compose (build.args.API_URL).
ARG API_URL=http://api:8000
ENV API_URL=$API_URL
RUN npm run build

# ---- Runner (production : .next/standalone/server.js) ----
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# Serveur autonome + fichiers statiques (public et .next/static servis par server.js)
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
