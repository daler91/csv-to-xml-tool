"""
XML validator and fixer utility for SBA Counseling Information forms.
This module helps validate and fix common XML structure issues.
"""

import os
import sys
import xml.etree.ElementTree as ET
from lxml import etree
from defusedxml.lxml import parse as defused_parse
import logging # Keep standard logging import for levels like logging.INFO
import re

# Logger will be instantiated in main() using ConversionLogger
# logger = logging.getLogger(__name__) # To be replaced

from logging_util import ConversionLogger # Import ConversionLogger

def validate_against_xsd(xml_file, xsd_file):
    """
    Validate XML against an XSD schema.
    
    Args:
        xml_file: Path to the XML file
        xsd_file: Path to the XSD schema file
        
    Returns:
        Tuple (is_valid, errors)
    """
    try:
        # Parse the XSD schema
        parser = etree.XMLParser(resolve_entities=False)
        xmlschema_doc = etree.parse(xsd_file, parser=parser)
        xmlschema = etree.XMLSchema(xmlschema_doc)
        
        # Parse the XML file
        xml_doc = etree.parse(xml_file, parser=parser)
        
        # Validate
        is_valid = xmlschema.validate(xml_doc)
        
        # Get validation errors
        errors = []
        if not is_valid:
            for error in xmlschema.error_log:
                errors.append(f"Line {error.line}: {error.message}")
        
        return is_valid, errors
    except Exception as e:
        return False, [f"Validation error: {str(e)}"]

def extract_validation_details(error_message):
    """
    Extract element names and expected elements from a validation error message.
    
    Args:
        error_message: The validation error message
        
    Returns:
        Tuple (invalid_element, expected_elements)
    """
    invalid_match = re.search(r"Invalid content was found starting with element '([^']+)'", error_message)
    expected_match = re.search(r"One of '{([^}]+)}' is expected", error_message)
    
    invalid_element = invalid_match.group(1) if invalid_match else None
    expected_elements = expected_match.group(1).split(', ') if expected_match else []
    
    return invalid_element, expected_elements

def fix_client_intake_element_order(xml_file, output_file=None):
    """
    Fix the order of elements in the ClientIntake section according to the XSD schema.
    
    Args:
        xml_file: Path to the XML file
        output_file: Path to save the fixed XML file (if None, will modify the original)
        
    Returns:
        Boolean indicating success
    """
    if output_file is None:
        output_file = xml_file
    
    try:
        # Parse the XML file
        tree = ET.parse(xml_file)
        root = tree.getroot()
        
        # Define the correct order of elements in ClientIntake
        client_intake_order = [
            'Race', 'Ethnicity', 'Sex', 'Disability', 'MilitaryStatus', 
            'BranchOfService', 'Media', 'Internet', 'CurrentlyInBusiness', 
            'CurrentlyExporting', 'CompanyName', 'BusinessType', 
            'BusinessOwnership', 'ConductingBusinessOnline', 
            'ClientIntake_Certified8a', 'Employee_Owned', 'TotalNumberOfEmployees',
            'NumberOfEmployeesInExportingBusiness', 'ClientAnnualIncomePart2',
            'LegalEntity', 'Rural_vs_Urban', 'FIPS_Code', 'CounselingSeeking',
            'ExportCountries'
        ]
        
        # Process each CounselingRecord
        for counseling_record in root.findall('CounselingRecord'):
            client_intake = counseling_record.find('ClientIntake')
            if client_intake is not None:
                # Reorder elements in ClientIntake
                reorder_elements(client_intake, client_intake_order)
        
        # Save the fixed XML
        tree.write(output_file, encoding='utf-8', xml_declaration=True)
        return True
    except Exception as e:
        logger.error(f"Error fixing XML file: {str(e)}")
        return False

def add_missing_required_elements(client_intake, record_id):
    """
    Add any missing required elements to ClientIntake.
    (Function moved from fix-sba-xml.py)
    
    Args:
        client_intake: ClientIntake element
        record_id: ID of the counseling record (for logging)
    """
    # Define required elements and their default values
    # This list might need to be configurable or expanded later.
    required_elements = {
        'CurrentlyInBusiness': 'No', 
        # Add other known required elements for ClientIntake here if they have simple defaults
    }
    
    elements_added = False
    for tag, default_value in required_elements.items():
        if client_intake.find(tag) is None:
            logger.info(f"Record {record_id}: Adding missing required element '{tag}' with default '{default_value}'")
            ET.SubElement(client_intake, tag).text = default_value
            elements_added = True
    return elements_added

def fix_client_intake_element_order(xml_file, output_file=None, add_missing_elements_flag=False):
    """
    Fix the order of elements in the ClientIntake section according to the XSD schema.
    Optionally adds missing required elements.
    
    Args:
        xml_file: Path to the XML file
        output_file: Path to save the fixed XML file (if None, will modify the original)
        add_missing_elements_flag: If True, add missing required elements.
        
    Returns:
        Boolean indicating success
    """
    if output_file is None:
        output_file = xml_file
    
    try:
        # Parse the XML file
        tree = ET.parse(xml_file)
        root = tree.getroot()
        
        # Define the correct order of elements in ClientIntake
        client_intake_order = [
            'Race', 'Ethnicity', 'Sex', 'Disability', 'MilitaryStatus', 
            'BranchOfService', 'Media', 'Internet', 'CurrentlyInBusiness', 
            'CurrentlyExporting', 'CompanyName', 'BusinessType', 
            'BusinessOwnership', 'ConductingBusinessOnline', 
            'ClientIntake_Certified8a', 'Employee_Owned', 'TotalNumberOfEmployees',
            'NumberOfEmployeesInExportingBusiness', 'ClientAnnualIncomePart2',
            'LegalEntity', 'Rural_vs_Urban', 'FIPS_Code', 'CounselingSeeking',
            'ExportCountries'
        ]
        
        # Process each CounselingRecord
        for counseling_record in root.findall('CounselingRecord'):
            record_id_element = counseling_record.find('PartnerClientNumber')
            record_id = record_id_element.text if record_id_element is not None else "UNKNOWN_RECORD"
            
            client_intake = counseling_record.find('ClientIntake')
            if client_intake is not None:
                if add_missing_elements_flag:
                    add_missing_required_elements(client_intake, record_id)
                # Reorder elements in ClientIntake
                reorder_elements(client_intake, client_intake_order)
        
        # Save the fixed XML
        tree.write(output_file, encoding='utf-8', xml_declaration=True)
        return True
    except Exception as e:
        logger.error(f"Error fixing XML file: {str(e)}")
        return False

def reorder_elements(parent, element_order):
    """
    Reorder child elements according to the specified order.
    
    Args:
        parent: Parent element
        element_order: List of element names in the correct order
    """
    # Create a dictionary to store elements by tag name
    elements = {}
    for child in list(parent):
        tag = child.tag
        if tag in elements:
            # If we already have this tag, it's a list of elements
            if isinstance(elements[tag], list):
                elements[tag].append(child)
            else:
                elements[tag] = [elements[tag], child]
        else:
            elements[tag] = child
        
        # Remove the child from the parent
        parent.remove(child)
    
    # Add elements back in the correct order
    for tag in element_order:
        if tag in elements:
            if isinstance(elements[tag], list):
                # Add all elements with this tag
                for element in elements[tag]:
                    parent.append(element)
            else:
                # Add the single element
                parent.append(elements[tag])
    
    # Add any remaining elements that weren't in the order list
    for tag, element in elements.items():
        if tag not in element_order:
            if isinstance(element, list):
                for item in element:
                    parent.append(item)
            else:
                parent.append(element)

def check_element_order(parent, element_order):
    """
    Check if elements are in the correct order.
    
    Args:
        parent: Parent element
        element_order: List of element names in the correct order
        
    Returns:
        Boolean indicating if there are ordering issues
    """
    # Get tags of child elements
    child_tags = [child.tag for child in parent]
    
    # Find elements from order list that exist in the XML
    expected_order = [tag for tag in element_order if tag in child_tags]
    
    # Check if the actual order matches the expected order
    # This simple check assumes all expected_order elements are present and in sequence.
    # A more robust check might be needed if elements can be optional and still affect order.
    current_pos_in_xml = 0
    for i, tag_in_expected_order in enumerate(expected_order):
        try:
            # Find the current tag's first occurrence in the actual child_tags list
            # starting from where the last tag was found.
            idx = child_tags.index(tag_in_expected_order, current_pos_in_xml)
            current_pos_in_xml = idx + 1 
        except ValueError:
            # Tag in expected_order is not in child_tags (or not after the previous one)
            # This might indicate an issue or an optional element not present.
            # For strict ordering of present elements, this is an issue.
            return True # Order issue or missing element that breaks sequence
            
    # Check if all elements from child_tags that are in element_order are in the correct sequence
    # This is a more complex check. The current logic in fix-sba-xml.py is simpler:
    last_index_in_parent = -1
    for tag_in_schema_order in element_order: # Iterate through the schema-defined order
        try:
            # Find the first occurrence of this tag in the parent's children
            indices_in_parent = [i for i, child in enumerate(parent) if child.tag == tag_in_schema_order]
            if not indices_in_parent:
                continue # This element is not in the parent, skip
            
            current_element_first_index = indices_in_parent[0]
            
            if current_element_first_index < last_index_in_parent:
                return True # Element appeared sooner than a preceding element in schema order
            last_index_in_parent = current_element_first_index
            
            # Additionally, ensure all instances of this tag are contiguous if that's a requirement
            # (The current reorder logic groups them, so this check might be for pre-existing state)
            # For now, just checking first occurrence order.

        except ValueError:
            # Element from element_order not found in parent, which is fine if it's optional.
            pass 
            
    return False  # No order issues based on first occurrence

def process_directory(input_dir, output_dir=None, recursive=False, pattern="*.xml", xsd_file=None, fix=False, add_missing_elements_flag=False):
    """
    Process all XML files in a directory.
    (Function adapted from fix-sba-xml.py)

    Args:
        input_dir: Input directory containing XML files
        output_dir: Output directory for fixed files (default: same as input, overwrites if fix is True)
        recursive: Whether to recursively process subdirectories
        pattern: File pattern to match
        xsd_file: Path to XSD schema for validation (optional)
        fix: Boolean, if True, fix the XML files.
        add_missing_elements_flag: Boolean, if True and fix is True, add missing elements.
        
    Returns:
        Number of files processed successfully.
    """
    import glob
    import os
    
    logger.info(f"Processing XML files in directory: {input_dir}")
    if recursive:
        logger.info(f"Recursive mode enabled, pattern: {pattern}")
    if output_dir:
        logger.info(f"Output directory: {output_dir}")
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            logger.info(f"Created output directory: {output_dir}")
            
    # Find XML files
    search_pattern = os.path.join(input_dir, "**", pattern) if recursive else os.path.join(input_dir, pattern)
    files = glob.glob(search_pattern, recursive=recursive)
    
    logger.info(f"Found {len(files)} XML files to process.")
    
    processed_count = 0
    for file_path in files:
        logger.info(f"--- Processing file: {file_path} ---")
        
        current_output_path = file_path
        if output_dir:
            rel_path = os.path.relpath(file_path, input_dir)
            current_output_path = os.path.join(output_dir, rel_path)
            # Ensure output subdirectory exists
            os.makedirs(os.path.dirname(current_output_path), exist_ok=True)

        # Validate original file if XSD is provided
        if xsd_file:
            logger.info(f"Validating original file {file_path} against {xsd_file}...")
            is_valid, errors = validate_against_xsd(file_path, xsd_file)
            if is_valid:
                logger.info(f"Original file {file_path} is valid.")
            else:
                logger.warning(f"Original file {file_path} is NOT valid. Errors: {errors}")

        if fix:
            logger.info(f"Attempting to fix {file_path} -> {current_output_path}")
            fix_success = fix_client_intake_element_order(file_path, current_output_path, add_missing_elements_flag)
            if fix_success:
                logger.info(f"Successfully fixed {file_path}, saved to {current_output_path}")
                # Re-validate if XSD provided and file was fixed
                if xsd_file:
                    logger.info(f"Re-validating fixed file {current_output_path} against {xsd_file}...")
                    is_valid_after_fix, errors_after_fix = validate_against_xsd(current_output_path, xsd_file)
                    if is_valid_after_fix:
                        logger.info(f"Fixed file {current_output_path} is valid.")
                    else:
                        logger.error(f"Fixed file {current_output_path} is NOT valid after fixing. Errors: {errors_after_fix}")
                processed_count += 1
            else:
                logger.error(f"Failed to fix {file_path}")
        elif not xsd_file: # If not fixing and no XSD, then we are just listing files.
            logger.info(f"File {file_path} found (no fix requested, no XSD for validation).")
            processed_count +=1 # Count as processed for listing purposes
            
    logger.info(f"Finished processing directory. {processed_count} files processed successfully (or listed).")
    return processed_count

def main():
    """Main entry point for the script."""
    import argparse
    
    parser = argparse.ArgumentParser(description='XML Validator and Fixer for SBA Counseling Information.')
    
    # Input: single file or directory
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument('--xmlfile', help='Path to a single XML file to process.')
    input_group.add_argument('--directory', help='Path to a directory of XML files to process.')

    # XSD for validation
    parser.add_argument('--xsd', help='Path to the XSD schema file for validation.')
    
    # Output options
    parser.add_argument('--output', help='Path to save the fixed XML file (for single file mode) or output directory (for directory mode).')
    
    # Directory processing options
    parser.add_argument('--recursive', '-r', action='store_true', help='Recursively process subdirectories (used with --directory).')
    parser.add_argument('--pattern', default="*.xml", help='File pattern for XML files (default: *.xml, used with --directory).')

    # Fixing options
    parser.add_argument('--fix', action='store_true', help='Enable fixing of XML files (currently fixes ClientIntake element order).')
    parser.add_argument('--add-missing', action='store_true', help='When fixing, also add missing required elements in ClientIntake (e.g., CurrentlyInBusiness).')
    
    # Logging options
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], 
                        default='INFO', help='Logging level.')
    
    args = parser.parse_args()
    
    # Setup logger using ConversionLogger
    log_level_val = getattr(logging, args.log_level.upper(), logging.INFO)
    # For xml-validator, default to console-only logging unless a --log-file arg is added later
    logger = ConversionLogger(
        logger_name="XMLValidator",
        log_level=log_level_val,
        log_to_file=False 
    ).logger # Get the actual logger instance
    
    if args.directory:
        # Process directory
        logger.info(f"Mode: Processing directory '{args.directory}'")
        output_dir_for_process = args.output # If None, process_directory handles it (in-place if fix is True)
        
        process_directory(
            input_dir=args.directory,
            output_dir=output_dir_for_process,
            recursive=args.recursive,
            pattern=args.pattern,
            xsd_file=args.xsd,
            fix=args.fix,
            add_missing_elements_flag=args.add_missing
        )
    elif args.xmlfile:
        # Process single file
        logger.info(f"Mode: Processing single file '{args.xmlfile}'")
        
        # Validate original file if XSD is provided
        if args.xsd:
            logger.info(f"Validating {args.xmlfile} against {args.xsd}...")
            is_valid, errors = validate_against_xsd(args.xmlfile, args.xsd)
            if is_valid:
                logger.info("XML is valid!")
            else:
                logger.error(f"XML is not valid. Found {len(errors)} errors:")
                for i, error_msg in enumerate(errors, 1):
                    logger.error(f"Error {i}: {error_msg}")
                    invalid_element, expected_elements = extract_validation_details(error_msg)
                    if invalid_element: # expected_elements can be empty
                        logger.info(f"  Invalid element: '{invalid_element}'")
                    if expected_elements:
                         logger.info(f"  Expected elements: {', '.join(expected_elements)}")
        
        # Fix the XML file if requested
        if args.fix:
            # Determine output path for single file mode
            # If --output is not provided, fix in-place (output_file = args.xmlfile)
            # If --output is provided, save to new file.
            output_file_path = args.output if args.output else args.xmlfile
            
            logger.info(f"Fixing XML file '{args.xmlfile}' and saving to '{output_file_path}'...")
            fix_success = fix_client_intake_element_order(
                args.xmlfile, 
                output_file_path, 
                add_missing_elements_flag=args.add_missing
            )
            
            if fix_success:
                logger.info("XML file fixed successfully!")
                # Re-validate if XSD provided and file was fixed
                if args.xsd:
                    logger.info(f"Re-validating fixed file {output_file_path} against {args.xsd}...")
                    is_valid_after_fix, errors_after_fix = validate_against_xsd(output_file_path, args.xsd)
                    if is_valid_after_fix:
                        logger.info(f"Fixed file {output_file_path} is valid.")
                    else:
                        logger.error(f"Fixed file {output_file_path} is NOT valid after fixing. Errors: {errors_after_fix}")
            else:
                logger.error(f"Failed to fix XML file '{args.xmlfile}'.")
        elif not args.xsd: # No fix, no xsd
             logger.info(f"XML file '{args.xmlfile}' processed (no fix requested, no XSD for validation).")

    else:
        # Should not happen due to mutually_exclusive_group
        logger.error("No input specified. Use --xmlfile or --directory.")
        parser.print_help()

if __name__ == "__main__":
    main()