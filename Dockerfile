# Stage 1: Builder
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies for asyncmy
RUN apt-get update && apt-get install -y gcc pkg-config default-libmysqlclient-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.nori.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime
FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies for asyncmy
RUN apt-get update && apt-get install -y default-libmysqlclient-dev && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local
COPY . .

# Run as a non-privileged user — limits the blast radius of a container
# escape and satisfies Semgrep dockerfile.security.missing-user (p/security-audit).
# chown is needed because COPY runs as root; gunicorn workers spawn under `nori`.
RUN useradd --create-home --uid 1000 nori && chown -R nori:nori /app
USER nori

EXPOSE 8000

CMD ["gunicorn", "asgi:app", "-c", "gunicorn.conf.py", "--chdir", "rootsystem/application"]
