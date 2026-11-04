"""Shared application logger; importing it never initializes a database."""
import logging

logger = logging.getLogger("smart_tkb")
logger.setLevel(logging.INFO)
