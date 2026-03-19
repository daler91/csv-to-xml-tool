import os

with open("src/validation_report.py", "r") as f:
    content = f.read()

import re

# We will rewrite the generate_html_report function
# and add helper functions.

new_methods = """
    def _generate_html_header(self):
        \"\"\"Generate the HTML header and styles.\"\"\"
        return f\"\"\"<!DOCTYPE html>
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
    <p>Generated on: {{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}}</p>
\"\"\"

    def _generate_summary_section(self, summary):
        \"\"\"Generate the summary section HTML.\"\"\"
        return f\"\"\"
    <div class="summary">
        <h2>Summary</h2>
        <p>Total records processed: <strong>{{summary['total_records']}}</strong></p>
        <p>Successfully processed: <strong class="success">{{summary['successful_records']}} ({{summary['success_rate']:.1f}}%)</strong></p>
        <p>Failed records: <strong class="error">{{summary['failed_records']}}</strong></p>
        <p>Total errors: <strong class="error">{{summary['error_count']}}</strong></p>
        <p>Total warnings: <strong class="warning">{{summary['warning_count']}}</strong></p>
    </div>
\"\"\"

    def _generate_category_table(self, title, categories):
        \"\"\"Generate a table for issue categories.\"\"\"
        if not categories:
            return ""

        html_content = f\"\"\"
    <h2>{{title}}</h2>
    <table>
        <tr>
            <th>Category</th>
            <th>Count</th>
        </tr>
\"\"\"
        for category, count in sorted(categories.items(), key=lambda x: x[1], reverse=True):
            html_content += f\"\"\"        <tr>
            <td>{{category}}</td>
            <td>{{count}}</td>
        </tr>
\"\"\"
        html_content += "    </table>\\n"
        return html_content

    def _generate_issues_table(self):
        \"\"\"Generate the detailed issues table.\"\"\"
        if not self.issues:
            return ""

        html_content = \"\"\"
    <h2>Detailed Issues</h2>
    <table>
        <tr>
            <th>Record ID</th>
            <th>Severity</th>
            <th>Category</th>
            <th>Field</th>
            <th>Message</th>
        </tr>
\"\"\"

        # Sort issues by severity (errors first) and then by record ID
        sorted_issues = sorted(self.issues, key=lambda x: (0 if x['severity'] == 'error' else 1, x['record_id']))

        for issue in sorted_issues:
            severity_class = "error" if issue['severity'] == 'error' else "warning"
            html_content += f\"\"\"        <tr>
            <td>{{issue['record_id']}}</td>
            <td class="{{severity_class}}">{{issue['severity'].upper()}}</td>
            <td>{{issue['category']}}</td>
            <td>{{issue['field_name']}}</td>
            <td>{{issue['message']}}</td>
        </tr>
\"\"\"

        html_content += "    </table>\\n"
        return html_content

    def generate_html_report(self, output_dir="."):
        \"\"\"
        Generate an HTML report of validation issues.

        Args:
            output_dir: Directory to save the HTML report

        Returns:
            Path to the created HTML file
        \"\"\"
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

        html_content += \"\"\"</body>
</html>
\"\"\"

        # Write HTML content to file
        with open(html_file, 'w') as f:
            f.write(html_content)

        return html_file
"""

start_str = '    def generate_html_report(self, output_dir="."):'
end_str = '# Create a default validator instance'

start_idx = content.find(start_str)
end_idx = content.find(end_str)

new_content = content[:start_idx] + new_methods + '\n' + content[end_idx:]

with open("src/validation_report.py", "w") as f:
    f.write(new_content)
