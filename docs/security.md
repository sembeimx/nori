# Seguridad y Limitadores

Nori proporciona middlewares de seguridad esenciales ya activados para proteger cada endpoint contra ataques web comunes y abusos de red, desde cabeceras seguras hasta rate limiters elásticos.

## Cabeceras de Seguridad (Security Headers)
Al arrancar, Nori inyecta en todo `Response` el `SecurityHeadersMiddleware`. Está habilitado y blinda pasivamente tu app Web con defaults férreos para Headers:

* **X-Content-Type-Options:** `nosniff` (Previene ataques basados en sniffeo y camuflaje MIME malicioso).
* **X-Frame-Options:** `DENY` (Aislamiento absoluto ante ataques de Clickjacking o Cross-Iframe).
* **X-XSS-Protection:** `1; mode=block`
* **Referrer-Policy:** `strict-origin-when-cross-origin` (Cuida enrutamiento y exposición pasiva ante analítica e intrusión externa cruzada).
* **Strict-Transport-Security (HSTS):** Impone conexión cifrada local durante 1 Año para browsers que detecten el flag.

## Compartición de Recursos Cruzados (CORS)

Exclusivamente activado si Nori se usa como un back-end API o si requiere peticiones *AJAX Fetch* entre dominios distanciados o puertos diferentes.

Solución: Inyecta explícitamente tú (o tus) dominios Front-End oficiales en tu macrovariable ambiente en la raíz primaria de configuración.

`.env`:
```text
CORS_ORIGINS=http://localhost:3000,https://app.com_front
```
(El omitir esta fila en los archivos o dejarla sin poblar, automáticamente inhabilitará cualquier bypass de seguridad cross-origin negando fetch y blindándolo `Same-Site`).

---

## Limitador Distribuido de Solicitudes (Rate Limiter `@throttle`)

Detención de escalamientos maliciosos Brute Force, Scripts Scraping y Overload DoS en los controladores de autenticación.

La directiva `@throttle("Cantidad/Ventana")` rastrea contadores de Request y arroja status bloqueados `HTTP 429 Too Many Requests` (HTML amigable u API Json si se pide Accept).

El bloqueo es unificado **Por Endpoint + Por Dirección IP Dinámica**. Si un Bot intenta adivinar tu endpoint global `/login` 5 veces con passwords rotos, su dirección IP local estará denegada solo para seguir intentando `/login` mientras Nori le otorga y prioriza banda ancha para iterar rutas lícitas adyacentes como `/dashboard` u `/products` simultáneamente.

```python
from core.http.throttle import throttle

class AuthController:

    @throttle('5/minute')   # Limita a solo 5 intentos limpios en ventana minúto.
    async def login_api_post(self, request):
        return await Log(...)

    @throttle('100/hour')   # Acota consumo intensivo a clientes en recursos API.
    async def get_report_xlsx(self, request):
        return
```

### Backends Centrales o Escalables

El Rate Limiter por defecto cuenta en `Dictionary` de memoria de Python. Esta solución "Memory" basta como limitador seguro en monolitos limitados en recursos o máquinas unificadas pequeñas.

Pero si escalas tu despliegue Nori bajo **Docker Swarm**,  o múltiples réplicas (Workers Gunicorn balanceados en Cluster), puedes optar de forma instantánea inyectando configuración `redis` unificada sin afectar ó tocar el código original de los controladores, para que contadores actúen a su vez centralizados entre múltiples máquinas aisladas sobre una única latencia.

`.env`:
```test
THROTTLE_BACKEND=redis
REDIS_URL=redis://localhost:6379 
```
