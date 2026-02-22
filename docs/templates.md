# Plantillas y Frontend (Jinja2)

Nori utiliza el sistema de templates **Jinja2** estándar de la industria. Cada ruta puede responder pintando un archivo HTML con diccionarios contextuales variables servidos desde el controlador.

La jerarquía base reside en la carpeta general del framework `/rootsystem/templates/`.

## Herencias y Bloques 

Al igual que Blade (Laravel) o Twig (Symfony), los archivos Jinja2 recomiendan operar en herencias `base.html` e iterar variables hijo `{% extends %}`.

**`base.html` (Layout Base)**:
Construye la envolvente del portal, con *placeholders* titulados llamados `{% block %}`:
```html
<!DOCTYPE html>
<html lang="es">
<head>
    <title>{% block title %}Nori App{% endblock %}</title>
    <!-- Tus Inyecciones CSS Custom aquí -->
    {% block head %}{% endblock %} 
</head>
<body>
    <nav>...</nav>

    <main>
        <!-- Tu Contenido Hijo se renderiza aquí -->
        {% block content %}{% endblock %}
    </main>
</body>
</html>
```

**Hijo / View HTML (`home.html`)**:
Inicia inyectando el dictámen `extends` en la línea uno y satura sus propios overrides de contexto a voluntad:

```html
{% extends "base.html" %}

{% block title %}Dashboard Principal{% endblock %}

{% block content %}
    <h1>Listado de Clientes</h1>
    <!-- Más HTML... -->
{% endblock %}
```

## Variables, Bucles y Condicionales

Jinja2 provee una lógica mínima para renderizado de variables dinámicas transferidas por tu controlador, usando las llaves dobles `{{ variable }}` y bloques cerrados para if/for `{% instruccion %}`.

### If / Else
```html
{% if request.session.get('user_id') %}
    <p>¡Bienvenido Administrador!</p>
{% else %}
    <a href="/login">Inicia Sesión</a>
{% endif %}
```

*(Importante: Puedes notar que la variable global de Starlette Request viaja siempre pre-inyectada por Nori. No es necesario re-exportarla del controlador y puede usarse de inmediato, p/ej `request.url.path` o `request.session`).*

### Bucles For (Ciclos Colección o Querysets)
```html
<ul>
    {% for usuario in total_usuarios %}
        <li><a href="/user/{{ usuario.id }}">{{ usuario.name }}</a></li>
    {% else %}
        <li>La lista está vacía — no hay usuarios registrados.</li>
    {% endfor %}
</ul>
```

### URLs y Links Dinámicos
Llamando `url_for` sobre el componente Request.

```html
<a href="{{ request.url_for('editar_cliente', cliente_id=123) }}">Click para Editar</a>
```

## Archivos Estáticos Nativo (StaticFiles)

Cualquier archivo css, javascript, logotipo svg o mp4 de multimedia que no necesite compilación debería copiarse puro en `rootsystem/static/`.

```
rootsystem/
    static/
        css/style.css
        js/app.js
        images/logo_nori.png
```

Nori expone el tag estático frontalmente sin rutas abstractas innecesarias:
```html
<!-- En base.html, dentro de <head> -->
<link rel="stylesheet" href="/static/css/style.css">

<!-- Renderizado de Imágenes -->
<img src="/static/images/logo_nori.png" alt="Logotipo Startup">
```

## Custom Error Pages

Al pasar la configuración `.env` de Nori a `DEBUG=false` en un servidor de Producción, tu sitio ocultará los Interactive Exception Tracebacks arrojando y compilando instantáneamente los planteles de la carpeta Raiz de Templates (`404.html` para un "Not Found" o URLs falsas, y `500.html` protegiendo crashes inesperados de base de datos contra los hackers).

Su implementación no difiere de un HTML normal extendido de base con el fin de retener intacto y pulcro el look de tu aplicación nativa mientras proteges su estado de crash (Ocultándolo al usuario final y renderizando su propio dashboard intacto de emergencia).
