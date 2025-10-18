"""
Módulo de logging estruturado para Rocinha Entrega

Configura logging com diferentes níveis e formatos para desenvolvimento e produção.
"""

import logging
import sys
import os
from pathlib import Path
from typing import Optional


def setup_logger(name: str = "rocinha_entrega", level: Optional[str] = None) -> logging.Logger:
    """
    Configura e retorna um logger estruturado.
    
    Args:
        name: Nome do logger (padrão: "rocinha_entrega")
        level: Nível de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
               Se não informado, usa a variável de ambiente LOG_LEVEL
    
    Returns:
        Logger configurado
    
    Exemplo:
        >>> from shared.logger import logger
        >>> logger.info("Bot iniciado")
        >>> logger.error("Erro ao processar entrega", exc_info=True)
    """
    logger = logging.getLogger(name)
    
    # Evita configurar múltiplas vezes
    if logger.handlers:
        return logger
    
    # Determina nível de log
    if level is None:
        level = os.getenv("LOG_LEVEL", "INFO").upper()
    
    log_level = getattr(logging, level, logging.INFO)
    logger.setLevel(log_level)
    
    # Handler para console (stdout)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    
    # Formato baseado no ambiente
    environment = os.getenv("ENVIRONMENT", "development")
    
    if environment == "production":
        # Formato estruturado para produção (facilita parsing)
        formatter = logging.Formatter(
            '%(asctime)s | %(name)s | %(levelname)s | %(filename)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    else:
        # Formato legível para desenvolvimento
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    # Previne propagação para o root logger
    logger.propagate = False
    
    return logger


# ═══════════════════════════════════════════════════════════
# LOGGER GLOBAL
# ═══════════════════════════════════════════════════════════
# Importe este logger em qualquer arquivo do projeto:
# from shared.logger import logger
# logger.info("Mensagem de log")
logger = setup_logger()


def log_function_call(func):
    """
    Decorator para logar entrada e saída de funções (útil para debugging).
    
    Exemplo:
        @log_function_call
        def processar_entrega(package_id: int):
            # ... código ...
    """
    import functools
    
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        func_name = func.__name__
        logger.debug(f"Chamando {func_name} com args={args}, kwargs={kwargs}")
        try:
            result = func(*args, **kwargs)
            logger.debug(f"{func_name} retornou: {result}")
            return result
        except Exception as e:
            logger.error(f"Erro em {func_name}", exc_info=True)
            raise
    
    return wrapper


def log_async_function_call(func):
    """
    Decorator para logar entrada e saída de funções assíncronas.
    
    Exemplo:
        @log_async_function_call
        async def cmd_relatorio(update, context):
            # ... código ...
    """
    import functools
    
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        func_name = func.__name__
        logger.debug(f"Chamando {func_name} (async)")
        try:
            result = await func(*args, **kwargs)
            logger.debug(f"{func_name} concluído")
            return result
        except Exception as e:
            logger.error(f"Erro em {func_name}", exc_info=True)
            raise
    
    return wrapper


# ═══════════════════════════════════════════════════════════
# HELPERS DE LOGGING
# ═══════════════════════════════════════════════════════════

def log_bot_command(command_name: str, user_id: int, user_name: str = "Unknown"):
    """Log padronizado para comandos do bot"""
    logger.info(f"Comando /{command_name} executado por {user_name} (ID: {user_id})")


def log_database_query(query_type: str, table: str, duration_ms: float = None):
    """Log padronizado para queries de banco de dados"""
    if duration_ms:
        logger.debug(f"Query {query_type} em {table} - {duration_ms:.2f}ms")
    else:
        logger.debug(f"Query {query_type} em {table}")


def log_api_request(method: str, path: str, status_code: int, duration_ms: float = None):
    """Log padronizado para requisições HTTP"""
    if duration_ms:
        logger.info(f"{method} {path} - {status_code} - {duration_ms:.2f}ms")
    else:
        logger.info(f"{method} {path} - {status_code}")


# ═══════════════════════════════════════════════════════════
# EXEMPLOS DE USO
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Testes do logger
    logger.debug("Esta é uma mensagem DEBUG")
    logger.info("Esta é uma mensagem INFO")
    logger.warning("Esta é uma mensagem WARNING")
    logger.error("Esta é uma mensagem ERROR")
    logger.critical("Esta é uma mensagem CRITICAL")
    
    # Teste com exceção
    try:
        1 / 0
    except Exception as e:
        logger.error("Erro capturado", exc_info=True)
    
    # Teste dos helpers
    log_bot_command("relatorio", 123456789, "João Silva")
    log_database_query("SELECT", "package", 15.5)
    log_api_request("GET", "/route/123/packages", 200, 45.2)
