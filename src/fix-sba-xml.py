#!/usr/bin/env python3
"""
SBA XML Fixer - A utility to fix common XML issues in SBA counseling records.

This script fixes element ordering issues in SBA counseling XML files according to the
SBA_NEXUS_Counseling XSD schema.
"""

import os
import sys

import argparse
import logging # Keep standard logging import for levels like logging.INFO
from datetime import datetime

# Local setup_logging will be removed.
# from .logging_util import logger # Default instance not used here.
from .logging_util import ConversionLogger # Import ConversionLogger

# Import necessary functions from xml_validator
# Note: If xml_validator.py is in the same directory or PYTHONPATH, this should work.
# Otherwise, sys.path manipulations might be needed, or a proper package structure.
try:
    from .xml_validator import fix_client_intake_element_order as validator_fix_order
    from .xml_validator import process_directory as validator_process_directory
except ImportError:
    # Fallback or error handling if xml_validator is not found directly
    # This might happen if they are not in the same directory and PYTHONPATH isn't set up.
    # For this tool's context, we assume they are accessible.
    print("Error: Could not import from xml_validator. Ensure it's in the Python path.")
    sys.exit(1)


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description='Fix SBA counseling XML files')
    
    # File/directory selection arguments
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument('--file', '-f', help='Path to a single XML file to fix')
    input_group.add_argument('--directory', '-d', help='Path to a directory of XML files to fix')
    
    # Output options
    parser.add_argument('--output', '-o', help='Path to save the fixed XML file/directory')
    parser.add_argument('--no-backup', action='store_true', help='Do not create backup of original file')
    
    # Directory processing options
    parser.add_argument('--recursive', '-r', action='store_true', help='Recursively process subdirectories')
    parser.add_argument('--pattern', default="*.xml", help='File pattern for XML files (default: *.xml)')
    
    # Logging options
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], 
                        default='INFO', help='Logging level')
    parser.add_argument('--log-file', action='store_true', help='Save log to file')
    
    return parser.parse_args()


def setup_logger(args):
    """Set up the logger based on command-line arguments."""
    log_level_val = getattr(logging, args.log_level.upper(), logging.INFO)
    # Determine log file path for ConversionLogger
    # fix-sba-xml.py had a --log-file flag which meant "create a timestamped file in current dir"
    log_file_path_for_fixer = None
    if args.log_file: # This flag means "enable file logging"
        # We let ConversionLogger handle the timestamped name in the default "logs" dir
        # or a more specific path could be constructed if needed.
        # For now, just enabling it will use ConversionLogger's default naming.
        # To precisely match old behavior (log in current dir):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file_path_for_fixer = f"sba_xml_fixer_wrapper_{timestamp}.log"

    return ConversionLogger(
        logger_name="SBAXMLFixerWrapper",
        log_level=log_level_val,
        log_to_file=args.log_file, # True if --log-file is present
        log_file_path=log_file_path_for_fixer # Specific path if needed, else None
    ).logger # Get the actual logger instance


def process_single_file(args, logger, mimic_original_add_missing):
    """Process a single XML file."""
    logger.info(f"[fix-sba-xml wrapper] Processing single file: {args.file}")

    output_file_path = args.output if args.output else args.file

    # Backup logic (simplified, xml-validator doesn't handle backups directly in its fix function)
    if not args.no_backup and output_file_path == args.file:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"{args.file}.{timestamp}.bak.fromwrapper"
        try:
            import shutil
            shutil.copy2(args.file, backup_file)
            logger.info(f"[fix-sba-xml wrapper] Created backup at {backup_file}")
        except Exception as e:
            logger.warning(f"[fix-sba-xml wrapper] Could not create backup: {str(e)}")

    fix_success = validator_fix_order(
        xml_file=args.file,
        output_file=output_file_path,
        add_missing_elements_flag=mimic_original_add_missing # Match original behavior
    )

    if fix_success:
        logger.info(f"[fix-sba-xml wrapper] Successfully fixed XML file: {output_file_path} (via xml_validator)")
        return 0
    else:
        logger.error("[fix-sba-xml wrapper] Failed to fix XML file (via xml_validator)")
        return 1


def process_directory(args, logger, always_fix, mimic_original_add_missing):
    """Process a directory of XML files."""
    logger.info(f"[fix-sba-xml wrapper] Processing directory: {args.directory} (via xml_validator)")
    # Note: The new process_directory in xml-validator does not handle backups internally.
    # Backups were handled per-file in the old fix-sba-xml.py if output_dir was None.
    # This wrapper will not replicate the backup functionality for directory mode to keep it thin.
    # Users should rely on xml-validator's output directory behavior.
    if args.output and not os.path.exists(args.output):
         os.makedirs(args.output)
         logger.info(f"[fix-sba-xml wrapper] Created output directory: {args.output}")

    count = validator_process_directory(
        input_dir=args.directory,
        output_dir=args.output, # Pass output dir. If None, xml-validator will modify in-place.
        recursive=args.recursive,
        pattern=args.pattern,
        xsd_file=None, # fix-sba-xml didn't use XSD for its directory processing.
        fix=always_fix,
        add_missing_elements_flag=mimic_original_add_missing # Match original behavior
    )
    logger.info(f"[fix-sba-xml wrapper] Successfully processed {count} XML files (via xml_validator)")
    return 0


def main():
    """Command-line entry point."""
    args = parse_arguments()
    logger = setup_logger(args)
    
    # Note: fix-sba-xml.py implicitly always fixes and adds missing elements.
    # We map its behavior to the new flags in xml-validator.
    always_fix = True
    always_add_missing = True # Based on original behavior of fix_client_intake_section
                              # which didn't have a flag to disable add_missing_required_elements.
                              # However, add_missing_required_elements was not actually called in fix_client_intake_section.
                              # For now, we'll set it to True to match the spirit of "fixing".
                              # This might need review based on desired behavior for this wrapper.
                              # The original fix_client_intake_section did not call add_missing_required_elements.
                              # So, to truly mimic, always_add_missing should be False.
                              # Let's assume for now the goal is to use the "full fix" capability.
                              # Re-evaluating: The original fix_client_intake_section in fix-sba-xml.py
                              # did NOT call add_missing_required_elements. So, to be a true wrapper,
                              # this should be False.
    mimic_original_add_missing = False

    try:
        if args.file:
            return process_single_file(args, logger, mimic_original_add_missing)
        elif args.directory:
            return process_directory(args, logger, always_fix, mimic_original_add_missing)
            
    except Exception as e:
        logger.error(f"[fix-sba-xml wrapper] Error: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
