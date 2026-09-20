FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE_URL
ARG ATC_COMMIT_SHA=local
ARG VITE_PRIMARY_STOREFRONT_SLUG=demo
ARG VITE_LEGAL_OPERATOR_NAME
ARG VITE_PRIVACY_CONTACT_EMAIL
ARG VITE_PRIVACY_EFFECTIVE_DATE=2026-07-23
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_RELEASE_ID=$ATC_COMMIT_SHA
ENV VITE_PRIMARY_STOREFRONT_SLUG=$VITE_PRIMARY_STOREFRONT_SLUG
ENV VITE_LEGAL_OPERATOR_NAME=$VITE_LEGAL_OPERATOR_NAME
ENV VITE_PRIVACY_CONTACT_EMAIL=$VITE_PRIVACY_CONTACT_EMAIL
ENV VITE_PRIVACY_EFFECTIVE_DATE=$VITE_PRIVACY_EFFECTIVE_DATE
# The managed production host runs inside a tight nested pids cgroup. The
# locale checker is synchronous, so avoid Node's default libuv worker pool
# consuming build-time thread slots needed by the rest of the Compose stack.
# The managed production host builds inside a nested Docker cgroup with a
# very small PID/thread budget.  Keep esbuild's Go runtime single-process
# during the image build; this only affects build-time parallelism and does
# not change the runtime worker/concurrency settings of the web container.
RUN GOMAXPROCS=1 UV_THREADPOOL_SIZE=1 npm run build

FROM nginxinc/nginx-unprivileged:1.29.4-alpine
USER root
COPY --chown=101:101 nginx.conf /etc/nginx/conf.d/default.conf
RUN rm -rf /usr/share/nginx/html \
    && mkdir -p /usr/share/nginx/html \
    && chown 101:101 /usr/share/nginx/html
COPY --chown=101:101 --from=build /app/dist /opt/atc-dist
COPY --chown=101:101 --chmod=755 docker-entrypoint.d/20-sync-static.sh /docker-entrypoint.d/20-sync-static.sh
USER 101
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
CMD ["nginx", "-g", "daemon off;"]
