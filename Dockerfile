# syntax=docker/dockerfile:1
# One Dockerfile for every Python service: `docker build --build-arg SERVICE=catalog .`
#
# Builds behind a TLS-intercepting proxy can pass its CA bundle as a build secret:
#   docker build --secret id=extra_ca,src=/path/to/ca.pem ...

ARG PYTHON_IMAGE=docker.io/library/python:3.13-slim

FROM ${PYTHON_IMAGE} AS build
ARG SERVICE
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -f /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install --no-cache-dir --root-user-action=ignore uv==0.11.32
WORKDIR /src
COPY pyproject.toml uv.lock ./
COPY libs libs
COPY services services
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=secret,id=extra_ca,required=false \
    if [ -f /run/secrets/extra_ca ]; then export SSL_CERT_FILE=/run/secrets/extra_ca; fi; \
    uv sync --frozen --no-dev --no-editable --package "shopfront-${SERVICE}"

FROM ${PYTHON_IMAGE}
ARG SERVICE
RUN useradd --system --uid 10001 --no-create-home app
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 SERVICE=${SERVICE}
USER app
EXPOSE 8000
CMD ["sh", "-c", "exec \"$SERVICE\""]
