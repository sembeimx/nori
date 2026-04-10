"""
Example custom command — rename this file (remove the _ prefix) to activate.

Custom commands live in the ``commands/`` directory and are auto-discovered
by the CLI. Each file must export two functions:

    register(subparsers)  — adds the argparse subparser(s)
    handle(args)          — executes the command logic

Usage after renaming to ``hello.py``::

    python3 nori.py hello
    python3 nori.py hello --name World
"""
from __future__ import annotations


def register(subparsers) -> None:
    """Register the command with argparse."""
    parser = subparsers.add_parser('hello', help='Say hello (example command)')
    parser.add_argument('--name', default='Nori', help='Name to greet')


def handle(args) -> None:
    """Execute the command."""
    print(f"Hello, {args.name}!")
