FROM node:22-alpine AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
ARG ORIGIN
# Env vars are validated during build analysis; real values are injected at runtime.
RUN ORIGIN=$ORIGIN PUBLIC_SUPABASE_URL= PUBLIC_SUPABASE_ANON_KEY= pnpm build && pnpm prune --prod

FROM node:22-alpine
WORKDIR /app
COPY --from=build /app/build ./build
COPY --from=build /app/node_modules ./node_modules
COPY package.json ./
ENV PORT=3000
EXPOSE 3000
CMD ["node", "build"]
