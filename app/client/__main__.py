#!/usr/bin/env python3
"""Ponto de entrada de linha de comando (CLI) para o pacote Homelab Client.

Permite execução direta via `python3 -m app.client [args]` ou `python3 app/client [args]`.
"""

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.client.menus import main

if __name__ == "__main__":
    main()
