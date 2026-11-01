"""Módulo de Logging Estruturado Centralizado do Homelab.

Fornece configuração e instanciamento padronizado de loggers conforme as
diretrizes de conformidade e DEBT-04, aplicando o formato canônico:
`[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s`.
"""

import logging
from pathlib import Path
import sys
from typing import List, Optional, Union

__all__: List[str] = [
    "HOMELAB_LOG_FORMAT",
    "HOMELAB_DATE_FORMAT",
    "setup_logging",
    "get_logger",
]

HOMELAB_LOG_FORMAT: str = "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s"
HOMELAB_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    level: int = logging.INFO,
    log_file: Optional[Union[str, Path]] = None,
) -> None:
    """Configura o sistema de logging com o formatador canônico do Homelab.

    Garante configuração determinística do root logger com `StreamHandler`
    e, opcionalmente, `FileHandler` com codificação UTF-8.

    Args:
        level: Nível de severidade de log (padrão: logging.INFO).
        log_file: Caminho opcional para gravação persistente em arquivo de log.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove handlers existentes no root para evitar duplicação em reconfigurações
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(fmt=HOMELAB_LOG_FORMAT, datefmt=HOMELAB_DATE_FORMAT)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(level)
    root_logger.addHandler(stream_handler)

    if log_file:
        file_path = Path(log_file)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(file_path), encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Retorna uma instância configurada de `logging.Logger` para o módulo especificado.

    Se o logger raiz ainda não possuir nenhum handler configurado, inicializa
    a configuração padrão do Homelab chamando `setup_logging()`.

    Args:
        name: Nome do componente ou módulo requerente (geralmente __name__).

    Returns:
        logging.Logger: Instância tipada do logger do módulo.
    """
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        setup_logging()
    return logging.getLogger(name)
