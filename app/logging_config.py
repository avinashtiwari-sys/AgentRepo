import logging
import sys
from logging.handlers import TimedRotatingFileHandler

def setup_logging():
    """Configure structured logging for the application."""
    logger = logging.getLogger("gtmflow")
    logger.setLevel(logging.INFO)

    # Prevent duplicate handlers if setup is called multiple times
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File Handler (daily rotation, keep 30 days)
    file_handler = TimedRotatingFileHandler(
        "gtmflow.log", when="midnight", interval=1, backupCount=30
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger

# Initialize logger
logger = setup_logging()
