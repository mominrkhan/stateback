# syntax=docker/dockerfile:1.7
ARG SOURCE_DATE_EPOCH=0
FROM node:24.6.0-alpine@sha256:51dbfc749ec3018c7d4bf8b9ee65299ff9a908e38918ce163b0acfcd5dd931d9 AS build
ARG SOURCE_DATE_EPOCH
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.31-alpine3.24@sha256:f972e5322b9797dc2a6b830030094426437b1ae7032e4644496395336ac6fdac
ARG SOURCE_DATE_EPOCH
ARG STATEBACK_VERSION=0.1.0
ARG STATEBACK_SOURCE_REVISION=unknown
LABEL org.opencontainers.image.title="Stateback operator frontend" \
      org.opencontainers.image.version="${STATEBACK_VERSION}" \
      org.opencontainers.image.source="https://github.com/mominrkhan/stateback" \
      org.opencontainers.image.revision="${STATEBACK_SOURCE_REVISION}" \
      org.opencontainers.image.licenses="MIT"
COPY --from=build /frontend/dist /usr/share/nginx/html
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --chown=101:101 LICENSE /licenses/LICENSE
USER 101:101
EXPOSE 8080
