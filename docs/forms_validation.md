# Formularios, CSRF y Validación

Nori cuenta con un agresivo motor de validación declarativa (inspirado al 100% en el sistema Pipe-Separated de Laravel) y un ecosistema nativo contra vulnerabilidades CSRF en los envíos de Estado.

## Protección CSRF Obligatoria

Toda respuesta de servidor de un Controlador Nori que emita un Formulario con un action en método `POST` debe obligadamente despachar por el diccionario de contexto la etiqueta de seguridad hacia Jinja2.

```python
from core.auth.csrf import csrf_field

# Renderizando mi html GET vacío al visitante
return templates.TemplateResponse(request, 'auth/miform.html', {
    'csrf_field': csrf_field(request.session)
})
```

En el respectivo HTML, usarás la etiqueta global, que inyectará en tiempo real el input `hidden` del Hash Dinámico.

```html
<form method="POST">
    {{ csrf_field|safe }}  <!-- No olvides el |safe para rendedizar el TAG -->
    
    <label>Usuario</label>
    <input type="text" name="usr">
    
    <button type="submit">Enviar</button>
</form>
```

Si el servidor detecta que en el archivo de Rutas el Endpoint `miform` se envía por `POST`, e intuye omitido u obsoleto el `_csrf_token` oculto, detendrá en seco la ejecución protegiendo tus esquemas de Base de Datos y devolviendo `403 Forbidden` JSON/HTML de rechazo inminente.

## Validación Declarativa Pipe-Separated (`validate`)

Al capturar diccionarios form en `request.form()` tu controlador se delega al validador genérico, pasándole las reglas con cadenas delimitadas por Pipes `|`.

```python
from core.http.validation import validate

async def process_form(self, request: Request):
    
    # 1. Obtenemos el diccionario entero enviado desde Jinja Form
    raw_form = dict(await request.form())
    
    # 2. Validación central e inyección del esquema de fallas
    errores = validate(raw_form, {
        'username': 'required|min:4|max:20',
        'email': 'required|email|max:255',
        'password': 'required|min:8',
        'confirm_password': 'required|matches:password',
        'age': 'numeric',
        'role': 'required|in:admin,editor,user',
    })
    
    # 3. Decision Tree
    if errores:
        # Repoblamos el form actual incluyendo los strings pre-validados.
        return templates.TemplateResponse(request, 'miform.html', {
            'csrf_field': csrf_field(request.session),
            'errors': errores,
            'usuarioname_enviado': raw_form.get('username', '')
        })

    # Si todo validó correctamente, operamos a base de datos.
```

### Reglas Incluidas Nativas

| Regla Declarada | Función Operativa |
| :---: | :--- |
| `required` | Bloquea strings vacíos o parámetros Keys omitidos en envío del Request Formulario. |
| `min:N` | Establece un Count limitante Límite de carácteres menor a `N`. |
| `max:N` | Acota que el string no desborde con Overflow `N`. |
| `email` | RegEx de verificación estricta oficial Email String (`name@domain.tld`). |
| `numeric` | Admite Integer y Decimales nativos parseables de la Key en el diccionario Web. |
| `matches:campo_b` | Cross-check de valididad total equitativo (Ej `matches:password_antigua`). |
| `in:op,op2` | Forzamiento de Enums Estáticos de Opciones delimitados por CSV (Ej: `in:activo,vetado,suspendido`). |

### Template: Mostrando Errores Visuales
Dentro de Jinja2, dado que has alimentado al template nuevamente con un diccionario `{campo: ['error 1', 'error 2']}`, basta por revisar la Key.

```html
<form method="POST">
    {{ csrf_field|safe }}
    
    <input name="email" value="{{ usr_correo|default('') }}" />
    {% if errors.email %}
        <!-- Mostrando la falla principal del bloque iterado Array Index 0 -->
        <span class="text-danger">{{ errors.email[0] }}</span> 
    {% endif %}
    
</form>
```
