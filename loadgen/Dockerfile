# syntax=docker/dockerfile:1
ARG PYTHON_IMAGE=docker.io/library/python:3.13-slim
FROM ${PYTHON_IMAGE}
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -f /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install --no-cache-dir --root-user-action=ignore locust==2.47.0
RUN useradd --system --uid 10001 --no-create-home locust
COPY locustfile.py /home/locust/locustfile.py
WORKDIR /home/locust
USER locust
# Runs until stopped: USERS shoppers against HOST, spawning 2 per second.
CMD ["sh", "-c", "exec locust --headless --only-summary -u \"${USERS:-20}\" -r 2 -H \"${HOST:-http://storefront:8080}\""]
