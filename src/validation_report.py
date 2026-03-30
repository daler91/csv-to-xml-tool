"""
Validation reporting for CSV to XML conversion.
This module tracks validation issues and generates reports.
"""

import csv
import os
from datetime import datetime
from collections import defaultdict, Counter

class ValidationTracker:
    """Tracks validation issues during the conversion process."""
    

    def __init__(self):
        """Initialize the validation tracker."""
        self.issues = []
        self.issue_counts = defaultdict(Counter)
        self.total_records = 0
        self.successful_records = 0
        self.failed_records = 0
        self.current_record_id = None

    def set_current_record_id(self, record_id):
        self.current_record_id = record_id
    
    def add_issue(self, record_id, severity, category, field_name, message):
        """
        Add a validation issue.
        
        Args:
            record_id: ID of the record with the issue
            severity: Issue severity (error, warning)
            category: Issue category (e.g., missing_data, invalid_format)
            field_name: Field with the issue
            message: Description of the issue
        """
        issue = {
            'record_id': record_id,
            'severity': severity,
            'category': category,
            'field_name': field_name,
            'message': message,
            'timestamp': datetime.now().isoformat()
        }
        
        self.issues.append(issue)
        self.issue_counts[severity][category] += 1
    
    def record_processed(self, success=True):
        """
        Record that a record was processed.
        
        Args:
            success: Whether the record was successfully processed
        """
        self.total_records += 1
        if success:
            self.successful_records += 1
    
    def get_summary(self):
        """
        Get a summary of validation issues.
        
        Returns:
            A dictionary with summary statistics
        """
        return {
            'total_records': self.total_records,
            'successful_records': self.successful_records,
            'failed_records': self.total_records - self.successful_records,
            'success_rate': (self.successful_records / self.total_records * 100) if self.total_records else 0,
            'error_count': sum(self.issue_counts['error'].values()),
            'warning_count': sum(self.issue_counts['warning'].values()),
            'errors_by_category': dict(self.issue_counts['error']),
            'warnings_by_category': dict(self.issue_counts['warning'])
        }
    
    def to_dict(self):
        """Return all tracker state as a JSON-serializable dict."""
        return {
            "summary": self.get_summary(),
            "issues": self.issues,
        }

    def print_summary(self):
        """Print a summary of validation issues to the console."""
        summary = self.get_summary()
        
        print("\n" + "="*50)
        print("VALIDATION SUMMARY")
        print("="*50)
        print(f"Total records processed: {summary['total_records']}")
        print(f"Successfully processed: {summary['successful_records']} ({summary['success_rate']:.1f}%)")
        print(f"Failed records: {summary['failed_records']}")
        print("\nIssue Summary:")
        print(f"  Errors: {summary['error_count']}")
        print(f"  Warnings: {summary['warning_count']}")
        
        if summary['errors_by_category']:
            print("\nErrors by category:")
            for category, count in sorted(summary['errors_by_category'].items(), key=lambda x: x[1], reverse=True):
                print(f"  {category}: {count}")
        
        if summary['warnings_by_category']:
            print("\nWarnings by category:")
            for category, count in sorted(summary['warnings_by_category'].items(), key=lambda x: x[1], reverse=True):
                print(f"  {category}: {count}")
        
        print("="*50)
    
    def save_issues_to_csv(self, output_dir="."):
        """
        Save all validation issues to a CSV file.
        
        Args:
            output_dir: Directory to save the CSV file
            
        Returns:
            Path to the created CSV file
        """
        if not self.issues:
            return None
        
        # Create output directory if it doesn't exist
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # Create CSV file with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_file = os.path.join(output_dir, f"validation_issues_{timestamp}.csv")
        
        # Define CSV columns
        fieldnames = ['record_id', 'severity', 'category', 'field_name', 'message', 'timestamp']
        
        # Write issues to CSV
        with open(csv_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for issue in self.issues:
                writer.writerow(issue)
        
        return csv_file
    

    def _generate_html_header(self):
        """Generate the HTML header and styles."""
        return f"""<!DOCTYPE html>
<html>
<head>
    <title>CSV to XML Conversion Validation Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1, h2 {{ color: #333; }}
        .summary {{ background-color: #f0f0f0; padding: 15px; border-radius: 5px; }}
        .success {{ color: green; }}
        .error {{ color: red; }}
        .warning {{ color: orange; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        tr:nth-child(even) {{ background-color: #f9f9f9; }}
    </style>
</head>
<body>
    <h1>CSV to XML Conversion Validation Report</h1>
    <p>Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
"""

    def _generate_summary_section(self, summary):
        """Generate the summary section HTML."""
        return f"""
    <div class="summary">
        <h2>Summary</h2>
        <p>Total records processed: <strong>{summary['total_records']}</strong></p>
        <p>Successfully processed: <strong class="success">{summary['successful_records']} ({summary['success_rate']:.1f}%)</strong></p>
        <p>Failed records: <strong class="error">{summary['failed_records']}</strong></p>
        <p>Total errors: <strong class="error">{summary['error_count']}</strong></p>
        <p>Total warnings: <strong class="warning">{summary['warning_count']}</strong></p>
    </div>
"""

    def _generate_category_table(self, title, categories):
        """Generate a table for issue categories."""
        if not categories:
            return ""

        html_content = f"""
    <h2>{title}</h2>
    <table>
        <tr>
            <th>Category</th>
            <th>Count</th>
        </tr>
"""
        for category, count in sorted(categories.items(), key=lambda x: x[1], reverse=True):
            html_content += f"""        <tr>
            <td>{category}</td>
            <td>{count}</td>
        </tr>
"""
        html_content += "    </table>\n"
        return html_content

    def _generate_issues_table(self):
        """Generate the detailed issues table."""
        if not self.issues:
            return ""

        html_content = """
    <h2>Detailed Issues</h2>
    <table>
        <tr>
            <th>Record ID</th>
            <th>Severity</th>
            <th>Category</th>
            <th>Field</th>
            <th>Message</th>
        </tr>
"""

        # Sort issues by severity (errors first) and then by record ID
        sorted_issues = sorted(self.issues, key=lambda x: (0 if x['severity'] == 'error' else 1, x['record_id']))

        for issue in sorted_issues:
            severity_class = "error" if issue['severity'] == 'error' else "warning"
            html_content += f"""        <tr>
            <td>{issue['record_id']}</td>
            <td class="{severity_class}">{issue['severity'].upper()}</td>
            <td>{issue['category']}</td>
            <td>{issue['field_name']}</td>
            <td>{issue['message']}</td>
        </tr>
"""

        html_content += "    </table>\n"
        return html_content

    def generate_html_report(self, output_dir="."):
        """
        Generate an HTML report of validation issues.

        Args:
            output_dir: Directory to save the HTML report
            
        Returns:
            Path to the created HTML file
        """
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        html_file = os.path.join(output_dir, f"validation_report_{timestamp}.html")

        summary = self.get_summary()

        # Assemble HTML content
        html_content = self._generate_html_header()
        html_content += self._generate_summary_section(summary)
        html_content += self._generate_category_table("Errors by Category", summary['errors_by_category'])
        html_content += self._generate_category_table("Warnings by Category", summary['warnings_by_category'])
        html_content += self._generate_issues_table()
        
        html_content += """</body>
</html>
"""
        
        # Write HTML content to file
        with open(html_file, 'w') as f:
            f.write(html_content)
        
        return html_file
