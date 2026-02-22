# Security and Limiters

Nori provides essential security middlewares already activated to protect each endpoint against common web attacks and network abuse, from secure headers to elastic rate limiters.

## Security Headers

Upon startup, Nori injects the `SecurityHeadersMiddleware` into every `Response`. It is enabled and passively shields your Web app with ironclad defaults for Headers:

* **X-Content-Type-Options:** `nosniff` (Prevents sniffing-based attacks and malicious MIME camouflage).
* **X-Frame-Options:** `DENY` (Absolute isolation against Clickjacking or Cross-Iframe attacks).
* **X-XSS-Protection:** `1; mode=block`
* **Referrer-Policy:** `strict-origin-when-cross-origin` (Safeguards routing and passive exposure against cross-external analytics and intrusion).
* **Strict-Transport-Security (HSTS):** Imposes local encrypted connection for 1 Year for browsers that detect the flag.

## Cross-Origin Resource Sharing (CORS)

Exclusively activated if Nori is used as an API back-end or if it requires *AJAX Fetch* requests between distant domains or different ports.

Solution: Explicitly inject your official Front-End domain(s) into your macro environment variable in the primary configuration root.

`.env`:
```text
CORS_ORIGINS=http://localhost:3000,https://app.com_front
```
(Omitting this row in the files or leaving it unpopulated will automatically disable any cross-origin security bypass denying fetch and shielding it `Same-Site`).

---

## Distributed Rate Limiter (`@throttle`)

Stops malicious Brute Force escalations, Scraping Scripts, and DoS Overloads on authentication controllers.

The `@throttle("Amount/Window")` directive tracks Request counters and returns blocked `HTTP 429 Too Many Requests` statuses (Friendly HTML or Json API if Accept is requested).

The block is unified **Per Endpoint + Per Dynamic IP Address**. If a Bot tries to guess your global `/login` endpoint 5 times with broken passwords, its local IP address will be denied *only* for continuing to try `/login` while Nori grants and prioritizes bandwidth to iterate adjacent lawful routes like `/dashboard` or `/products` simultaneously.

```python
from core.http.throttle import throttle

class AuthController:

    @throttle('5/minute')   # Limits to only 5 clean attempts in a minute window.
    async def login_api_post(self, request):
        return await Log(...)

    @throttle('100/hour')   # Restricts intensive consumption to clients in API resources.
    async def get_report_xlsx(self, request):
        return
```

### Central or Scalable Backends

The default Rate Limiter counts in a Python memory `Dictionary`. This "Memory" solution suffices as a secure limiter in resource-limited monoliths or small unified machines.

But if you scale your Nori deployment under **Docker Swarm**, or multiple replicas (Gunicorn Workers balanced in a Cluster), you can instantly opt by injecting unified `redis` configuration without affecting or touching the original controller code, so that counters act centrally between multiple isolated machines over a single latency.

`.env`:
```test
THROTTLE_BACKEND=redis
REDIS_URL=redis://localhost:6379 
```
