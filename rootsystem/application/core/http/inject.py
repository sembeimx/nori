import functools
import inspect

def inject():
    """
    Decorador utilitario de Inyección de Dependencias.
    Lee los Type Hints y nombres de argumentos del método del controlador
    para extraer e inyectar automáticamente datos desde el Request 
    (form_data, query_params, path_params) sin necesidad de variables globales.

    Ejemplo de uso en un controlador:
        @inject()
        async def create(self, request, form: dict, product_id: int):
            # 'form' será el dict() de request.form()
            # 'product_id' será extraído de path_params o query_params y convertido a int
            # ...
    """
    def decorator(func):
        sig = inspect.signature(func)
        
        @functools.wraps(func)
        async def wrapper(self, request, *args, **kwargs):
            injected_kwargs = {}
            
            # Recolectar datos FormData asíncronos de forma perezosa solo si se solicitan
            form_data = None
            needs_form = "form" in sig.parameters or any(
                p.annotation == dict for p in sig.parameters.values() if p.name not in ['self', 'request']
            )
            
            if needs_form:
                try:
                    form_data = dict(await request.form())
                except Exception:
                    form_data = {}
            
            # Analizar el signature y poblar argumentos
            for name, param in sig.parameters.items():
                # Omitimos auto inputs
                if name in ("self", "request") or name in kwargs:
                    continue
                
                # 1. Solicita Diccionario completo o Form
                if name == "form" or param.annotation == dict:
                    injected_kwargs[name] = form_data
                
                # 2. Solicita variable anclada a la URL (Path Params)
                elif name in request.path_params:
                    val = request.path_params[name]
                    if param.annotation != inspect.Parameter.empty:
                        try:
                            val = param.annotation(val)
                        except (ValueError, TypeError):
                            pass
                    injected_kwargs[name] = val
                
                # 3. Solicita variables de Query Param HTTP (?q=buscar)
                elif name in request.query_params:
                    val = request.query_params.get(name)
                    if param.annotation != inspect.Parameter.empty:
                        try:
                            val = param.annotation(val)
                        except (ValueError, TypeError):
                            pass
                    injected_kwargs[name] = val
                
                # 4. Fallback a parámetros base
                else:
                    if param.default != inspect.Parameter.empty:
                        injected_kwargs[name] = param.default
                    else:
                        injected_kwargs[name] = None
                        
            # Finalmente pasamos los valores computados de vuelta al controlador
            return await func(self, request, *args, **kwargs, **injected_kwargs)
        return wrapper
    return decorator
