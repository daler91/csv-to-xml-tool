# SBA Counseling and Training Data Conversion Tool

Converts SBA counseling and training CSV data into XSD-compliant XML files.

The tool ships in two forms:

- A **web application** (`apps/web`, `apps/worker`) — recommended for
  most users. Handles authentication, uploads, preview/mapping,
  validation reports, job history, and downloads via a browser.
- A **Python CLI** (`run.py`, `src/`) — the original interactive
  launcher, useful for power users and for scripting.

-----

## Web App (recommended)

The web app is a Next.js frontend backed by a FastAPI worker, Postgres,
and Redis — all wired up in `docker-compose.yml`.

### Run it locally

```bash
cp .env.example .env
# Edit .env to set DATABASE_URL, NEXTAUTH_SECRET, etc.
docker compose up
```

Then open <http://localhost:3000>, create an account, and upload a CSV.

### Download sample CSVs

Sample CSVs for each converter type live under
`apps/web/public/samples/` and are also linked from the landing page
and the dashboard empty state inside the app:

- `counseling-sample.csv` — individual counseling sessions (Form 641)
- `training-sample.csv` — aggregated training events (Form 888)
- `training-client-sample.csv` — per-attendee rows (Form 641)

### UX documentation

- [`UX_REVIEW.md`](./UX_REVIEW.md) — severity-ranked audit of the
  web app's user-facing surfaces.
- [`UX_IMPLEMENTATION_PLAN.md`](./UX_IMPLEMENTATION_PLAN.md) — the
  phased roadmap that sequences the UX review findings into
  executable slices.
- [`TECHNICAL_DEBT.md`](./TECHNICAL_DEBT.md) — code/security debt
  register, separate from UX concerns.

-----

## Python CLI

-----

## Quick Start (3 steps)

1. **Download** — On the GitHub page, click the green **Code** button → **Download ZIP**. Unzip the folder anywhere on your computer.

2. **Setup** (one time only) — Requires [Python](https://www.python.org/downloads/) (check **"Add Python to PATH"** during install).
   - **Windows:** Double-click `setup.bat`
   - **Mac/Linux:** Open a terminal in the folder and run: `pip install -r requirements.txt`

3. **Run** — Put your CSV file in the folder, then:
   - **Windows:** Double-click `run.bat`
   - **Mac/Linux:** Open a terminal in the folder and run: `python run.py`

   The tool will walk you through selecting your CSV file, conversion type, and optional XSD validation — no typing commands needed.

Your output XML and validation reports will be saved in the `output/` and `reports/` folders.

-----

## Key Features

  * **Dual Converters**:
      * **Counseling Data (Form 641)**: Converts detailed client counseling session data.
      * **Training Data**: Aggregates participant data from training events and converts it.
  * **Data Cleaning & Standardization**:
      * Formats dates to the required `YYYY-MM-DD` standard.
      * Cleans and validates phone numbers, numeric values, and percentages.
      * Standardizes state and country names to match schema enumerations (e.g., "IA" becomes "Iowa").
      * Truncates long text fields, like counselor notes, to meet maximum length requirements while preserving readability.
      * Correctly handles and splits multi-value fields from Salesforce (e.g., `Race` or `Services Provided`).
  * **XSD-Compliant XML Generation**:
      * Generates XML with elements in the precise order required by the schemas, preventing common `cvc-complex-type.2.4.a` validation errors.
      * Correctly maps CSV data to the appropriate XML tags based on an extensive mapping configuration.
      * Handles conditional logic, such as requiring a `BranchOfService` only when `MilitaryStatus` indicates service.
  * **Validation & Reporting**:
      * During conversion, it generates comprehensive validation reports in both CSV and HTML formats, detailing any issues found in the source data.
  * **XML Fixer Utility**:
      * Includes a standalone script (`fix_sba_xml.py`) to correct element ordering issues in existing XML files that do not conform to the schema.

-----

## Project Structure

```
.
├── run.py                         # Interactive launcher (start here!)
├── run.bat                        # Windows double-click shortcut
├── setup.bat                      # Windows one-time setup
├── src/
│   ├── converters/
│   │   ├── base_converter.py       # Base class for all converters
│   │   ├── counseling_converter.py # Logic for converting counseling data (Form 641)
│   │   └── training_converter.py   # Logic for converting training class data
│   ├── main.py                     # Main entry point to run the converters
│   ├── data_cleaning.py            # Functions for cleaning, formatting, and standardizing data
│   ├── data_validation.py          # Functions for validating data integrity
│   ├── xml_utils.py                # Helper functions for creating XML elements
│   ├── config.py                   # Central configuration for field mappings, defaults, and validation rules
│   ├── validation_report.py        # Module for tracking and reporting validation issues
│   ├── logging_util.py             # Configures application-wide logging
│   ├── fix_sba_xml.py              # Utility to fix element order in existing SBA XML files
│   └── xml_validator.py            # Utility to validate XML files against an XSD
├── tests/
│   ├── test_counseling_converter.py
│   ├── test_data_cleaning.py
│   ├── test_training_converter.py
│   └── test_xml_utils.py
└── README.md
```

-----

## How to Use

The primary entry point for the conversion is `src/main.py`.

### Prerequisites

  * Python 3.x
  * Pandas library (`pip install pandas`)

### Converting Data

1.  **Prepare your CSV file**. Ensure it contains the necessary columns as defined in `src/config.py`.

2.  **Run the `main.py` script** from your terminal, specifying the `converter_type`, and providing the input and output paths.

    **For Counseling Data (Form 641):**

    ```bash
    python -m src.main convert counseling --input /path/to/your/report.csv --output /path/to/output/counseling_data.xml
    ```

    **For Training Data:**

    ```bash
    python -m src.main convert training --input /path/to/your/training_report.csv --output /path/to/output/training_data.xml
    ```

### Fixing an Existing XML File

If you have an XML file that fails validation due to incorrect element order, use the `fix_sba_xml.py` script:

```bash
python -m src.fix_sba_xml --file /path/to/your/invalid.xml --output /path/to/output/fixed.xml
```

This will re-order the elements to match the schema requirements.

### Command-Line Arguments (`main.py`)

  * `converter_type`: The type of conversion to perform (`counseling` or `training`).
  * `--input, -i`: Path to the input CSV file.
  * `--output, -o`: (Optional) Path for the output XML file. If omitted, the XML will be saved in the same directory as the input file with a timestamp.
  * `--log-level`: Set the logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). Defaults to `INFO`.
  * `--report-dir`: Directory to save validation reports. Defaults to `reports/`.
  * `--log-dir`: Directory to save log files. Defaults to `logs/`.
