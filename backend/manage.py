#!/usr/bin/env python
"""Django 管理入口。"""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ.setdefault("DJANGO_SECRET_KEY", "dev-insecure-key")
    os.environ.setdefault("NOPS_CRYPTO_KEY", "dev-crypto-key-change-me-in-prod")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Activate the venv or use docker."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
