import functools
import inspect

def inject():
    """
    Dependency Injection utility decorator.
    Reads the Type Hints and argument names of the controller method
    to automatically extract and inject data from the Request 
    (form_data, query_params, path_params) without needing global variables.

    Usage example in a controller:
        @inject()
        async def create(self, request, form: dict, product_id: int):
            # 'form' will be the dict() from request.form()
            # 'product_id' will be extracted from path_params or query_params and cast to int
            # ...
    """
    def decorator(func):
        sig = inspect.signature(func)
        
        @functools.wraps(func)
        async def wrapper(self, request, *args, **kwargs):
            injected_kwargs = {}
            
            # Lazily collect async FormData only if requested
            form_data = None
            needs_form = "form" in sig.parameters or any(
                p.annotation == dict for p in sig.parameters.values() if p.name not in ['self', 'request']
            )
            
            if needs_form:
                try:
                    form_data = dict(await request.form())
                except Exception:
                    form_data = {}
            
            # Analyze signature and populate arguments
            for name, param in sig.parameters.items():
                # Skip auto inputs
                if name in ("self", "request") or name in kwargs:
                    continue
                
                # 1. Requests full Dictionary or Form
                if name == "form" or param.annotation == dict:
                    injected_kwargs[name] = form_data
                
                # 2. Requests URL-anchored variable (Path Params)
                elif name in request.path_params:
                    val = request.path_params[name]
                    if param.annotation != inspect.Parameter.empty:
                        try:
                            val = param.annotation(val)
                        except (ValueError, TypeError):
                            pass
                    injected_kwargs[name] = val
                
                # 3. Requests HTTP Query Param variables (?q=search)
                elif name in request.query_params:
                    val = request.query_params.get(name)
                    if param.annotation != inspect.Parameter.empty:
                        try:
                            val = param.annotation(val)
                        except (ValueError, TypeError):
                            pass
                    injected_kwargs[name] = val
                
                # 4. Fallback to base parameters
                else:
                    if param.default != inspect.Parameter.empty:
                        injected_kwargs[name] = param.default
                    else:
                        injected_kwargs[name] = None
                        
            # Finally, pass the computed values back to the controller
            return await func(self, request, *args, **kwargs, **injected_kwargs)
        return wrapper
    return decorator
