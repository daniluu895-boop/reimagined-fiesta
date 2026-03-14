import sys
from loguru import logger
import os

log_level = os.getenv("LOG_LEVEL", "INFO")

# Удаляем стандартный обработчик
logger.remove()

# Добавляем вывод в файл
logger.add(
    "logs/bot.log",
    format="[{time:YYYY-MM-DD HH:mm:ss}] [{level}] {message}",
    level=log_level,
    rotation="10 MB",
    compression="zip"
)

# Добавляем вывод в консоль
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - <level>{message}</level>",
    level=log_level
)