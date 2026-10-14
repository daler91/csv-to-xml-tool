#!/usr/bin/env python3
"""
SBA XML Fixer - A utility to fix common XML issues in SBA counseling records.

This script puts the elements of SBA counseling (Form 641) and training (Form 888)
XML files in the order their XSD requires, then checks each result against that
XSD. It exits non-zero when a file could not be fixed or still fails the schema.
"""

import os
import sys

import argparse
import logging
import xml.etree.ElementTree as ET
from datetime import datetime

# Ensure the script can be run from anywhere by adding its directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from logging_util import ConversionLogger # Import ConversionLogger
from path_safety import output_base, resolve_within

# Import necessary functions from xml_validator
from xml_validator import fix_and_revalidate as validator_fix_and_revalidate
from xml_validator import log_fix_result
from xml_validator import process_directory as validator_process_directory


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
        except OSError as e:
            logger.warning(f"[fix-sba-xml wrapper] Could not create backup: {str(e)}")

    result = validator_fix_and_revalidate(
        xml_file=args.file,
        output_file=output_file_path,
        add_missing_elements_flag=mimic_original_add_missing # Match original behavior
    )

    # It used to say "Successfully fixed" whenever the file was rewritten,
    # however the result then validated.
    if log_fix_result(result, args.file, output_file_path, logger):
        logger.info(f"[fix-sba-xml wrapper] Fixed XML file: {output_file_path} passes SBA's schema (via xml_validator)")
        return 0
    if result.ok:
        logger.error(f"[fix-sba-xml wrapper] {output_file_path} still fails SBA's schema (via xml_validator)")
    else:
        logger.error(f"[fix-sba-xml wrapper] Failed to fix XML file {args.file} (via xml_validator)")
    return 1


def process_directory(args, logger, always_fix, mimic_original_add_missing):
    """Process a directory of XML files."""
    logger.info(f"[fix-sba-xml wrapper] Processing directory: {args.directory} (via xml_validator)")
    # Note: The new process_directory in xml-validator does not handle backups internally.
    # Backups were handled per-file in the old fix-sba-xml.py if output_dir was None.
    # This wrapper will not replicate the backup functionality for directory mode to keep it thin.
    # Users should rely on xml-validator's output directory behavior.
    # Confine the output directory within the allowed base (CWE-22) before
    # creating it or handing it to the validator.
    output_dir = resolve_within(output_base(), args.output) if args.output else None
    if output_dir and not os.path.exists(output_dir):
         os.makedirs(output_dir)
         logger.info(f"[fix-sba-xml wrapper] Created output directory: {output_dir}")

    summary = validator_process_directory(
        input_dir=args.directory,
        output_dir=output_dir, # Pass output dir. If None, xml-validator will modify in-place.
        recursive=args.recursive,
        pattern=args.pattern,
        xsd_file=None, # Each fixed file is checked against the XSD its root element belongs to.
        fix=always_fix,
        add_missing_elements_flag=mimic_original_add_missing # Match original behavior
    )
    logger.info(f"[fix-sba-xml wrapper] {summary.describe()} (via xml_validator)")
    for path in summary.invalid:
        logger.error(f"[fix-sba-xml wrapper] Still fails SBA's schema: {path}")
    for path in summary.failed:
        logger.error(f"[fix-sba-xml wrapper] Could not be fixed: {path}")
    return 0 if summary.ok else 1


def main():
    """Command-line entry point."""
    args = parse_arguments()
    logger = setup_logger(args)
    
    always_fix = True
    # The original fix_client_intake_section did not add missing elements,
    # so we preserve that behavior here.
    mimic_original_add_missing = False

    try:
        if args.file:
            return process_single_file(args, logger, mimic_original_add_missing)
        elif args.directory:
            return process_directory(args, logger, always_fix, mimic_original_add_missing)
            
    except (OSError, ET.ParseError) as e:
        logger.error(f"[fix-sba-xml wrapper] Error: {str(e)}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
