# Contributing to Nori

Thank you for your interest in contributing to Nori.

## Getting Started

1. Fork the repository and clone your fork.
2. Create a feature branch from `main`.
3. Make your changes and commit them with clear, descriptive messages.
4. Run the test suite to ensure nothing is broken.
5. Submit a pull request against `main`.

## Requirements

- Python 3.9 or higher.
- Type hints are mandatory for all function signatures.
- Use `from __future__ import annotations` at the top of modules.

## Running Tests

```bash
pytest tests/
```

## Code Style

- Follow the existing patterns and conventions in the codebase.
- Controllers use `PascalCase` with a `Controller` suffix. Methods are `async snake_case`.
- Models use `PascalCase`. Table names are plural.
- Routes use dot-notation for names and require explicit `methods=`.

## Guidelines

- Keep pull requests focused on a single change.
- Do not compare Nori with other frameworks in code comments, documentation, or PR descriptions.
- All state-changing actions must use POST.
- Include tests for new functionality when applicable.

## Reporting Issues

Use the GitHub issue templates for bug reports and feature requests.
