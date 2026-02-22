#!/usr/bin/env python3
import sys
import os
import argparse

def serve():
    os.chdir('rootsystem/application')
    print("🚀 Booting up Nori Framework (Uvicorn) in development mode...")
    # --reload-dir templates forces browser reloading on html saves
    os.system('uvicorn asgi:app --reload --reload-dir ../templates --host 0.0.0.0 --port 8000')

def make_controller(name):
    filename = name.lower() + '.py'
    filepath = os.path.join('rootsystem', 'application', 'modules', filename)
    if os.path.exists(filepath):
        print(f"Error: {filepath} already exists.")
        return
    
    content = f"""from starlette.requests import Request
from starlette.responses import JSONResponse
from core.jinja import templates

class {name.capitalize()}Controller:

    async def list(self, request: Request):
        return JSONResponse({{"message": "{name} List"}})

    async def create(self, request: Request):
        pass
"""
    with open(filepath, 'w') as f:
        f.write(content)
    print(f"✅ Controller successfully created at: {filepath}")

def make_model(name):
    filename = name.lower() + '.py'
    filepath = os.path.join('rootsystem', 'application', 'models', filename)
    if os.path.exists(filepath):
        print(f"Error: {filepath} already exists.")
        return
    
    content = f"""from tortoise.models import Model
from tortoise import fields
from core.mixins.model import NoriModelMixin

class {name.capitalize()}(NoriModelMixin, Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=100)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = '{name.lower()}'
"""
    with open(filepath, 'w') as f:
        f.write(content)
    print(f"✅ Model {name} successfully created at: {filepath}")
    print(f"⚠️  Don't forget to import and register the model in rootsystem/application/models/__init__.py")

def main():
    parser = argparse.ArgumentParser(description="Nori Artisan CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: serve
    subparsers.add_parser("serve", help="Starts the server in development mode with Hot Reload enabled")

    # Command: make:controller
    parser_controller = subparsers.add_parser("make:controller", help="Creates a new basic Controller")
    parser_controller.add_argument("name", type=str, help="Entity name (e.g. Product)")

    # Command: make:model
    parser_model = subparsers.add_parser("make:model", help="Creates a new Tortoise ORM Model")
    parser_model.add_argument("name", type=str, help="Entity name (e.g. Product)")

    args = parser.parse_args()

    if args.command == "serve":
        serve()
    elif args.command == "make:controller":
        make_controller(args.name)
    elif args.command == "make:model":
        make_model(args.name)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
