# Servicios y Utilidades Core

Nori abstrae las operaciones más comunes de backend que suelen requerir librerías de terceros (envío de correos, gestión de subidas) en métodos limpios, seguros y nativos listos para usar en tus Controladores.

## Subida de Archivos Estáticos (Uploads)

Olvídate de parsear flujos de bytes multipart manualmente. La directiva pre-incorporada `save_upload` centraliza validaciones estrictas y escrituras asíncronas a disco. Mantiene configuraciones por defecto estrictas para evitar subidas de archivos perjudiciales (XSS/Shells PHP o Ejecutables).

### Implementación Base

En un flujo POST con formato de formulario HTML `<form enctype="multipart/form-data">`, utiliza `await request.form()` obteniendo así la instancia de `UploadFile`.

```python
from core.http.upload import save_upload

async def actualizar_avatar(self, request):
    form = await request.form()
    archivo_enviado = form.get('avatar_file') # Objeto de subida
    
    if not archivo_enviado.filename:
         return Error("Archivo requerido")

    respuesta = await save_upload(
        archivo_enviado,                 
        destination='avatars',           # Guardará en: /rootsystem/static/avatars/
        allowed=['jpg','png','jpeg'],    # Valida mime-types estrcitos + extensión
        max_size=2048576                 # Capacidad Max: 2 MB
    )

    if not respuesta['success']:
        # Falló el filtro de tamaño, o la terminación / MiME-Type no coincide.
        return Error(respuesta['error']) 
        
    # Guardado con éxito. Obtienes URL absoluta de lectura pública.
    print("Guardado en:", respuesta['filepath']) # Ej: '/static/avatars/1A2bC.jpg'
```

### Configuración Global (.env)
Puedes delimitar pasivamente topes máximos de upload para el servidor entero sobrescribiendo la configuración con `UPLOAD_MAX_SIZE` y alterando el path base con `UPLOAD_DIR`.

---

## Envíos de Correo Electrónico (SMTP)

Usualmente requeriría de librerías síncronas pesadas y paralizantes. Nori provee un utilitario de correo nativo (`send_mail`) respaldado por un despachador `aiosmtplib` totalmente asíncrono para mantener tu hilo principal intacto.

Además, ¡soporta renderizado directo de templates Jinja2 (HTML) por detrás!

### Configuración .env (Requerido)

```text
MAIL_HOST=smtp.mailgun.org
MAIL_PORT=587
MAIL_USER=postmaster@tu-dominio.com
MAIL_PASSWORD=secret
MAIL_FROM=Notificaciones Nori <hello@tu-dominio.com>
MAIL_TLS=true
```

### Uso Básico (Texto Plano)

Ideal para logs rápidos, recuperaciones de password vía API, o avisos de crash al administrador.
```python
from core.mail import send_mail

async def post(self, request):
    # Logica general ...

    # Disparo No-Bloqueante
    await send_mail(
        to='cliente_1@gmail.com',
        subject='Te damos la Bienvenida',
        body='Gracias por tu registro en el App!'
    )
```

### Mails Estilizados Avanzados HTML / Jinja2

Nori conectará con tus directorios del framework automáticamente; de esta forma un Diseñador puede codificar el look del mail en base a tablas visuales en un template clásico `/rootsystem/templates/mails/bienvenida.html` y tú en el backend simplemente dictas variables puras de Python.

```python
async def notificar_pago(self, request):

    resultado = await send_mail(
        to='ceo@miapp.com',
        subject='💰 Nueva venta registrada',
        template='mails/venta_html.html',   # Ruta relativa visual
        context={
            'nombre': 'Acme Corp',
            'monto': 150000.50
        }
    )

    if resultado:
        print("Enviado con exito vía SMTP de mailgun!")
    else:
        print("El despachador TLS falló, ver logs")
```
