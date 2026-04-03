from __future__ import annotations

"""
Logging utility for CSV to XML conversion.
This module provides configurable logging functionality for the conversion process.
"""

import logging
import os
from datetime import datetime

class ConversionLogger:
    """Handles logging for the CSV to XML conversion process and other utilities."""
    
    def __init__(self,
                 logger_name="conversion_logger",
                 log_level=logging.INFO,
                 log_to_file=True,
                 log_dir="logs",
                 log_file_path=None,
                 console_format='%(levelname)s: %(message)s',
                 file_format='%(asctime)s - %(name)s - %(levelname)s - %(message)s') -> None:
        """
        Initialize the logger.
        
        Args:
            logger_name: Name for the logger instance.
            log_level: The logging level (e.g., logging.INFO, logging.DEBUG).
            log_to_file: Whether to save logs to a file.
            log_dir: Directory to store log files if log_file_path is not specified.
            log_file_path: Specific path for the log file. Overrides log_dir and timestamped name.
            console_format: Format string for console handler.
            file_format: Format string for file handler.
        """
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(log_level)
        self.logger.handlers = []  # Clear existing handlers to avoid duplicates
        
        # Add console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_formatter = logging.Formatter(console_format)
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        # Determine if file logging is active
        effective_log_to_file = log_to_file or (log_file_path is not None)

        if effective_log_to_file:
            actual_log_file_path = log_file_path
            if actual_log_file_path:
                # Ensure directory for the specified log_file_path exists
                log_file_dir = os.path.dirname(actual_log_file_path)
                if log_file_dir and not os.path.exists(log_file_dir):
                    os.makedirs(log_file_dir)
            else:
                # Use log_dir and generate timestamped name
                if not os.path.exists(log_dir):
                    os.makedirs(log_dir)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                actual_log_file_path = os.path.join(log_dir, f"{logger_name}_{timestamp}.log")
            
            file_handler = logging.FileHandler(actual_log_file_path)
            file_handler.setLevel(log_level)
            file_formatter = logging.Formatter(file_format)
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)
            
            self.logger.info(f"Logging to file: {actual_log_file_path}")
    
    def info(self, message: str) -> None:
        """Log an info message."""
        self.logger.info(message)
    
    def warning(self, message: str, record_id: str | None = None) -> None:
        """
        Log a warning message.
        
        Args:
            message: The warning message
            record_id: Optional ID to identify the record with the issue
        """
        if record_id:
            self.logger.warning(f"[Record {record_id}] {message}")
        else:
            self.logger.warning(message)
    
    def error(self, message: str, record_id: str | None = None) -> None:
        """
        Log an error message.
        
        Args:
            message: The error message
            record_id: Optional ID to identify the record with the issue
        """
        if record_id:
            self.logger.error(f"[Record {record_id}] {message}")
        else:
            self.logger.error(message)
    
    def debug(self, message: str) -> None:
        """Log a debug message."""
        self.logger.debug(message)

# Default global logger instance (can be replaced by specific instantiations in scripts)
# This instance is for convenience if a script needs a quick logger without specific config.
# Most executable scripts should create their own configured instance.
logger = ConversionLogger(logger_name="default_app_logger", log_to_file=False)
