FROM python:3.12-slim

ARG KUBECTL_VERSION=v1.33.0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN apt-get update \
    && apt-get install --no-install-recommends --yes ca-certificates curl \
    && curl --fail --location --silent --show-error \
         "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
         --output /usr/local/bin/kubectl \
    && curl --fail --location --silent --show-error \
         "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl.sha256" \
         --output /tmp/kubectl.sha256 \
    && echo "$(cat /tmp/kubectl.sha256)  /usr/local/bin/kubectl" | sha256sum --check \
    && chmod 0755 /usr/local/bin/kubectl \
    && rm /tmp/kubectl.sha256 \
    && apt-get purge --auto-remove --yes curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --requirement requirements.txt \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin agent

COPY agent/ ./agent/
COPY entrypoint.sh ./entrypoint.sh
RUN chmod 0755 /app/entrypoint.sh

USER 10001:10001

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "-m", "agent.main"]
