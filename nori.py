#!/usr/bin/env python3
"""Nori CLI — thin bootstrap. All logic lives in core/cli.py."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'rootsystem', 'application'))
from core.cli import main

if __name__ == '__main__':
    main()
