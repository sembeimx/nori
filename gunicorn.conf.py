from multiprocessing import cpu_count

workers = cpu_count() * 2 + 1
worker_class = 'uvicorn.workers.UvicornWorker'
bind = '0.0.0.0:8000'

# Trust X-Forwarded-* headers from any upstream. Gunicorn propagates this
# value to the uvicorn worker, which would otherwise default to 127.0.0.1 only.
# Required when Nori runs behind a reverse proxy (Caddy, Nginx, Traefik, ALB)
# in a separate container or host — otherwise uvicorn reports scheme=http and
# Starlette url_for() generates absolute http:// URLs, which browsers block as
# mixed content on HTTPS pages.
#
# Safe in a container network because the only reachable upstream is the
# reverse proxy itself. On a single-host VPS with Nginx on 127.0.0.1, you
# may tighten this to "127.0.0.1".
#
# DO NOT leave this as "*" if port 8000 is reachable from outside your
# private network — an attacker can spoof X-Forwarded-For to bypass rate
# limits, audit logs, and IP-based ACLs. Either firewall the port or set
# the CIDR of your proxy.
forwarded_allow_ips = '*'
