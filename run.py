#!/usr/bin/env python3
"""
Simple interactive launcher for the CSV-to-XML conversion tool.
Designed for users who are not comfortable with command-line arguments.

Usage: just double-click or run "python run.py"
"""

import os
import sys
import glob
from datetime import datetime


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def print_banner():
    print("=" * 60)
    print("       SBA CSV-to-XML Conversion Tool")
    print("=" * 60)
    print()


def find_files(directory, extension):
    """Find files with the given extension in the directory."""
    pattern = os.path.join(directory, f"*{extension}")
    return sorted(glob.glob(pattern))


def pick_from_list(prompt, options, allow_custom=False):
    """Let the user pick from a numbered list."""
    print(prompt)
    print("-" * 40)
    for i, option in enumerate(options, 1):
        # Show just the filename, not the full path
        display = os.path.basename(option) if os.sep in option or '/' in option else option
        print(f"  {i}. {display}")
    if allow_custom:
        print(f"  {len(options) + 1}. Enter a custom file path")
    print()

    while True:
        choice = input("Enter your choice (number): ").strip()
        try:
            num = int(choice)
            if 1 <= num <= len(options):
                return options[num - 1]
            if allow_custom and num == len(options) + 1:
                custom = input("Enter the full file path: ").strip().strip('"').strip("'")
                if os.path.exists(custom):
                    return custom
                print(f"  File not found: {custom}")
                continue
        except ValueError:
            pass
        print("  Invalid choice. Please try again.")


def main():
    clear_screen()
    print_banner()

    # --- Step 1: Pick conversion type ---
    converter_types = {
        "Counseling (Form 641)": "counseling",
        "Training (Management Training Report)": "training",
    }
    type_names = list(converter_types.keys())
    chosen_name = pick_from_list(
        "Step 1: What type of data are you converting?",
        type_names
    )
    converter_type = converter_types[chosen_name]
    print(f"  -> {chosen_name}")
    print()

    # --- Step 2: Pick input CSV file ---
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_files = find_files(script_dir, ".csv")

    if csv_files:
        input_path = pick_from_list(
            "Step 2: Which CSV file do you want to convert?",
            csv_files,
            allow_custom=True
        )
    else:
        print("Step 2: No CSV files found in the current folder.")
        input_path = input("  Enter the full path to your CSV file: ").strip().strip('"').strip("'")

    if not os.path.exists(input_path):
        print(f"\n  ERROR: File not found: {input_path}")
        input("\nPress Enter to exit...")
        sys.exit(1)

    print(f"  -> {os.path.basename(input_path)}")
    print()

    # --- Step 3: Choose output location ---
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_output = os.path.join(script_dir, "output", f"{base_name}_{timestamp}.xml")

    print("Step 3: Where should the XML file be saved?")
    print(f"  Default: output/{os.path.basename(default_output)}")
    custom_output = input("  Press Enter for default, or type a custom path: ").strip().strip('"').strip("'")
    output_path = custom_output if custom_output else default_output
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    print(f"  -> {output_path}")
    print()

    # --- Step 4: Pick XSD for validation (optional) ---
    xsd_files = find_files(script_dir, ".xsd")
    xsd_path = None

    if xsd_files:
        print("Step 4: Would you like to validate the output against an XSD schema?")
        print("  1. Yes")
        print("  2. No, skip validation")
        print()
        validate_choice = input("Enter your choice (number): ").strip()
        if validate_choice == "1":
            xsd_path = pick_from_list(
                "\n  Which XSD schema file?",
                xsd_files
            )
            print(f"  -> {os.path.basename(xsd_path)}")
        else:
            print("  -> Skipping validation")
    print()

    # --- Confirm and run ---
    print("=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"  Type:    {chosen_name}")
    print(f"  Input:   {os.path.basename(input_path)}")
    print(f"  Output:  {output_path}")
    if xsd_path:
        print(f"  Schema:  {os.path.basename(xsd_path)}")
    else:
        print(f"  Schema:  (no validation)")
    print("=" * 60)
    print()
    confirm = input("Ready to convert? (Y/n): ").strip().lower()
    if confirm and confirm != 'y':
        print("Cancelled.")
        input("\nPress Enter to exit...")
        sys.exit(0)

    print()
    print("-" * 60)
    print("  CONVERTING...")
    print("-" * 60)
    print()

    # --- Run the conversion ---
    from src.logging_util import ConversionLogger
    from src.validation_report import ValidationTracker
    from src.converters.counseling_converter import CounselingConverter
    from src.converters.training_converter import TrainingConverter
    import logging

    converters = {
        "counseling": CounselingConverter,
        "training": TrainingConverter,
    }

    logger = ConversionLogger(
        logger_name="SBADataConverter",
        log_level=logging.INFO,
        log_dir=os.path.join(script_dir, "logs"),
        log_to_file=True
    ).logger

    validator = ValidationTracker()

    try:
        converter_class = converters[converter_type]
        converter = converter_class(logger, validator)
        converter.convert(input_path, output_path)
    except Exception as e:
        print(f"\n  ERROR during conversion: {e}")
        input("\nPress Enter to exit...")
        sys.exit(1)

    print()
    validator.print_summary()

    # Save reports
    report_dir = os.path.join(script_dir, "reports")
    os.makedirs(report_dir, exist_ok=True)
    csv_report = validator.save_issues_to_csv(report_dir)
    html_report = validator.generate_html_report(report_dir)

    # --- XSD Validation ---
    if xsd_path:
        print()
        print("-" * 60)
        print("  VALIDATING AGAINST XSD...")
        print("-" * 60)
        print()

        from src.xml_validator import validate_against_xsd
        _r = validate_against_xsd(output_path, xsd_path)
        is_valid, errors = _r["is_valid"], _r["errors"]

        if is_valid:
            print("  RESULT: XML is VALID!")
        else:
            print(f"  RESULT: XML has {len(errors)} validation error(s).")
            print()
            # Show first 10 errors in a user-friendly way
            for i, error in enumerate(errors[:10], 1):
                print(f"    {i}. {error}")
            if len(errors) > 10:
                print(f"    ... and {len(errors) - 10} more.")
            print()
            print("  The XML file was still saved. You may need to review")
            print("  the data in your CSV for the issues listed above.")

    # --- Final summary ---
    print()
    print("=" * 60)
    print("  DONE!")
    print("=" * 60)
    print()
    print(f"  XML file:  {output_path}")
    if html_report:
        print(f"  Report:    {html_report}")
    if csv_report:
        print(f"  Issues:    {csv_report}")
    print()
    input("Press Enter to exit...")


if __name__ == "__main__":
    main()
