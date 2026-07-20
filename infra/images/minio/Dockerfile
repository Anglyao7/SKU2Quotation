# syntax=docker/dockerfile:1.7
FROM golang:1.24.8-bookworm AS build

ARG MINIO_VERSION=RELEASE.2025-10-15T17-29-55Z
ENV CGO_ENABLED=0
RUN GOBIN=/out go install github.com/minio/minio@${MINIO_VERSION}

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10002 minio \
    && useradd --uid 10002 --gid minio --create-home --shell /usr/sbin/nologin minio \
    && mkdir -p /data \
    && chown minio:minio /data
COPY --from=build /out/minio /usr/local/bin/minio
USER 10002:10002
EXPOSE 9000 9001
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD ["curl", "--fail", "--silent", "http://127.0.0.1:9000/minio/health/live"]
ENTRYPOINT ["minio"]
CMD ["server", "/data", "--console-address", ":9001"]
