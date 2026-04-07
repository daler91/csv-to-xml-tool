"""
Main entry point for the CSV to XML conversion utility.

This module provides a command-line interface to select a converter
(e.g., for counseling or training data) and run the conversion process.
"""

import os
import argparse
import logging
import sys
from datetime import datetime

from .logging_util import ConversionLogger
from .validation_report import ValidationTracker
from .converters.counseling_converter import CounselingConverter
from .converters.training_converter import TrainingConverter
from .converters.training_client_converter import TrainingClientConverter

# Mapping of converter names to their classes
CONVERTERS = {
    "counseling": CounselingConverter,
    "training": TrainingConverter,
    "training-client": TrainingClientConverter,
}

def main():
    """
    Main function to parse arguments and orchestrate the conversion process.
    """
    parser = argparse.ArgumentParser(description="SBA Data Conversion Utility")
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")

    # --- Convert Command ---
    parser_convert = subparsers.add_parser("convert", help="Convert a CSV file to XML")
    parser_convert.add_argument(
        "converter_type",
        choices=CONVERTERS.keys(),
        help="The type of conversion to perform."
    )
    parser_convert.add_argument(
        "--input", "-i",
        required=True,
        help="Path to the input CSV file."
    )
    parser_convert.add_argument(
        "--output", "-o",
        help="Path for the output XML file. If omitted, it's saved next to the input file."
    )
    parser_convert.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default='INFO',
        help='Set the logging level.'
    )
    parser_convert.add_argument(
        '--log-dir',
        default='logs',
        help='Directory to save log files.'
    )
    parser_convert.add_argument(
        '--report-dir',
        default='reports',
        help='Directory to save validation reports.'
    )

    args = parser.parse_args()

    # --- Initialization ---
    log_level_val = getattr(logging, args.log_level.upper(), logging.INFO)
    logger = ConversionLogger(
        logger_name="SBADataConverter",
        log_level=log_level_val,
        log_dir=args.log_dir,
        log_to_file=True
    ).logger

    validator = ValidationTracker()

    logger.info(f"Starting '{args.converter_type}' conversion for: {args.input}")

    # --- File Path Handling ---
    if not os.path.exists(args.input):
        logger.error(f"Input file not found: {args.input}")
        sys.exit(1)

    if args.output:
        output_path = args.output
    else:
        csv_dir = os.path.dirname(args.input)
        base_name = os.path.splitext(os.path.basename(args.input))[0]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(csv_dir, f"{base_name}_{timestamp}.xml")

    # Ensure output directory exists
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # --- Conversion ---
    try:
        converter_class = CONVERTERS[args.converter_type]
        converter = converter_class(logger, validator)
        converter.convert(args.input, output_path)

        logger.info("Conversion process completed.")

        # --- Reporting ---
        validator.print_summary()

        os.makedirs(args.report_dir, exist_ok=True)
        csv_report = validator.save_issues_to_csv(args.report_dir)
        if csv_report:
            logger.info(f"Validation issues CSV report saved to: {csv_report}")

        html_report = validator.generate_html_report(args.report_dir)
        logger.info(f"Validation HTML report saved to: {html_report}")

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
