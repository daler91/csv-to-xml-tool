# Converting a CSV to SBA XML: the quick guide

You have a CSV export from Salesforce and need an XML file SBA Nexus/EDMIS will
accept. This page gets you there in about ten minutes, in plain steps. When you
want the detail behind a step, the links at the end go deeper.

There are two ways to convert:

- **The web app** — sign in, upload, download. Recommended, and what most of
  this page covers.
- **The desktop tool** — a double-click program on your own computer, for when
  you have no web app to sign in to. See
  [Using the desktop tool](#using-the-desktop-tool-instead).

Both run the same converter and give the same XML.

---

## Before you start

**1. Pick the right converter.** This matters more than anything else on this
page: the wrong one gives a confusing result, with nearly every column missing.

| You are reporting… | Pick | One CSV row is… |
|---|---|---|
| One-to-one advising sessions | **Counseling (Form 641)** | one session with one client |
| An event — a workshop, webinar or class — with attendee totals | **Training (Form 888)** | one attendee; the tool adds up the totals for you |
| Each attendee of an event as a counseling record | **Training Client (Form 641)** | one attendee |

Not sure? Read [Which one do I want?](./converters.md#which-one-do-i-want).

**2. Check the columns.** The tool reads the column names your Salesforce report
exports. A few must be present or the web app stops the conversion:

- **Counseling:** `Contact ID`, `Race`, `Ethnicity:`, `Gender`, `Disability`,
  `Veteran Status`, `Currently In Business?`, `Type of Session`, `Date`,
  `Duration (hours)`, `Name of Counselor`, `Language(s) Used`.
- **Training:** `Class/Event ID`.
- **Training Client:** `Contact ID` and `Class/Event ID`.

If your columns are named differently, that's fine — you can match them up in
the app. The full list is in [csv-reference.md](./csv-reference.md).

**3. Save it as a CSV.** The file must end in `.csv` and be under 50MB (unless
your administrator set a different limit). In Excel, choose **CSV UTF-8 (Comma
delimited)** when you save. Plain *CSV (Comma delimited)* works too, but the
tool then has to read it as an older character set, so check accented names
(José, Muñoz) in the preview; the results will carry a warning saying so.

Want to practice first? There is a sample CSV for each converter: **Download
sample CSV** on the app's home page, or **See sample** beside each converter
type when you upload.

---

## Convert in the web app

### 1. Sign in

Open the app and click **Create Account** the first time (your password needs at
least 8 characters, an uppercase letter, a number and a symbol), or **Sign In**.

### 2. Upload your CSV

Click **Convert** in the top bar. Pick your converter type, choose your file
under **CSV File**, and click **Upload & Preview**.

### 3. Check the preview

The preview shows your first 20 rows and three numbers:

- **Matched** — columns the tool recognized.
- **Missing** — columns the tool looks for but didn't find. Some are optional,
  so a number here is normal.
- **Extra** — columns the tool doesn't use. They are ignored, which is harmless.

Below that, **Data quality** lists problems found anywhere in the file — not
just the 20 rows shown — and what will happen to those rows.

- If **Missing** is 0, go to step 5.
- Otherwise, click **Map Columns** (step 4). It marks which of the missing
  columns are **Required** — one of those missing makes the conversion fail —
  and lets you point the tool at your own column when yours has a different
  name. If nothing required is missing, you can go straight to step 5.

### 4. Match up your columns (only if needed)

The mapping page lists every field the tool expects, each marked **Required**,
**Conditional** or **Optional**. For a field your file names differently, pick
your column under **Map From CSV Column**. The tool pre-fills its best guesses —
check each one, because a guess matches spelling, not meaning.

Click **Save Mapping & Continue** to go back to the preview. The preview's
numbers don't change after mapping; the mapping is applied when you convert.

> **Doing this every month?** Before you leave the page, type a name under
> **Save current mapping as** and click **Save template**. Next time, pick it
> under **Saved templates** and click **Apply**. (Or use **Apply last mapping**.)
> A template is never applied by itself.

### 5. Convert

Click **Confirm & Convert**. A progress page counts the records as they go, and
the results open by themselves when it finishes. You can leave the page; the
conversion keeps running, and the job is on your **Dashboard**.

### 6. Check the results, then download

Before you download, check three things:

1. **Is Successful the same as Total Records?** If not, the difference is the
   number of records *left out* of the XML. Each one is listed under **Errors**
   with the reason, usually ending "so the record was left out of the XML". Fix
   those rows (see [Fix and try again](#fix-and-try-again)), or accept that
   they won't be filed.
2. **Does XSD Validation say "XML is valid against the XSD schema"?** That
   means the file passes the same schema SBA validates against. If it says the
   XML *failed*, don't file it — see [troubleshooting.md](./troubleshooting.md).
3. **Read the Warnings.** A warning means the record was filed, but something in
   it is not exactly what your CSV said. Look hardest at two kinds:
   - **`fabricated_default`** — a value was filled in because your CSV didn't
     have one (for example, `0` for a missing loan amount). It goes to SBA, so
     make sure it's true.
   - **`downgraded_value`** — something your CSV gave was dropped or changed to
     fit SBA's rules.

When you're satisfied, click **Download XML**. That's the file you upload to
SBA.

> **Errors** counts problems, not records. One record can have several errors,
> and some errors leave the record in the file. Total Records minus Successful
> is the number to watch.

---

## Fix and try again

Most files need a round or two before they are clean.

1. Fix the rows the errors name, in Salesforce or in the CSV. The **Record**
   column tells you which row: its Contact ID, or, for a row without one,
   `Row_5` — the fifth row under the header, which is row 6 in Excel.
2. On the results page, click **Re-upload**, choose your fixed file, and click
   **Upload & Compare**. The converter type stays the same.
3. The new upload starts with no mapping: if you used one, **Apply last mapping**
   or your template.
4. Convert again. The results now show three tabs: **Resolved** (fixed since
   last time), **New** (appeared this time) and **Persistent** (still there).

Repeat until Successful equals Total Records, the XSD check passes, and every
warning left is one you accept.

---

## What the common messages mean

| You see | What it means | What to do |
|---|---|---|
| "Missing required column(s) for counseling: …" | A must-have column isn't in the file | Add it to your Salesforce report, or map your column to it (step 4) |
| "Missing required Contact ID." | A row has no Contact ID, so it can't be filed | Fill in the ID and re-upload |
| An error ending "…so the record was left out of the XML" | That record isn't in the file | Fix the value it names and re-upload |
| A warning ending "…so it was skipped" | A blank row, a repeated header, or a report title or footer line | Nothing — it wasn't a record |
| "The file is not UTF-8, so it was read as Windows-1252…" | Saved as plain *CSV (Comma delimited)* | Check accented names came through, or save as **CSV UTF-8** |
| "This file is larger than 50MB…" | The file is over the size limit | Split it into smaller batches |
| "That file isn't a CSV…" | The file doesn't end in `.csv` | Save it from Excel as a CSV |
| "The worker did not respond within the conversion time limit." | The file took too long | Split it into smaller batches |
| "Invalid email or password", with the right password | Too many sign-in attempts (10 in 15 minutes) | Wait 15 minutes |

Anything else: [troubleshooting.md](./troubleshooting.md) lists every message.

---

## Already have an XML file?

Click **Validate XML** in the top bar to check an existing file against SBA's
schema, without converting anything. Pick the form — **Counseling (Form 641)**,
which covers Training Client files too, or **Training (Form 888)** — choose the
`.xml` file and click **Validate**.

If a counseling file fails, **Attempt automatic fix** puts its elements in the
order SBA requires and checks it again. It never adds or changes a value, so a
missing value still fails. If it worked, **Download fixed XML**.

---

## Using the desktop tool instead

No sign-in, no internet needed once it's installed. Windows steps shown; on a
Mac or Linux, run `pip install -r requirements.txt` once, then `python run.py`.

1. **Install Python** from [python.org](https://www.python.org/downloads/). On
   Windows, tick **"Add Python to PATH"** during the install.
2. **Download the tool** — on GitHub, **Code → Download ZIP**, and unzip it
   anywhere.
3. **Set up once** — double-click `setup.bat`.
4. **Put your CSV in the same folder as `run.py`.**
5. **Double-click `run.bat`** and answer four questions:
   - **Step 1** — the type of data (the converter).
   - **Step 2** — which CSV file. Type its number.
   - **Step 3** — where to save. Press Enter for the default.
   - **Ready to convert? (Y/n)** — press Enter.
6. **Find your files** in the same folder: the XML in `output/`, and the report
   in `reports/` — open the `.html` file in your browser to read the errors and
   warnings.

> The desktop tool checks every record against SBA's schema as it converts, and
> leaves out any that would fail, but it doesn't print an overall pass or fail.
> To see one, copy the schema you need from the `schemas` folder into the folder
> with `run.py` (the counseling one for Training Client too) — the tool then asks
> a **Step 4** question and checks the file — or use the web app's
> **Validate XML** page.

More detail: [getting-started.md](./getting-started.md#the-desktop-cli) and
[cli.md](./cli.md).

---

## Before you file with SBA

- [ ] I used the right converter for what I'm reporting.
- [ ] **Successful** equals **Total Records**, or I know why each left-out record
      was left out.
- [ ] **XSD Validation** says the XML is valid.
- [ ] I read every `fabricated_default` and `downgraded_value` warning, and the
      values are true.
- [ ] My organization's location code is right. The tool files `249003` unless
      the CSV has a `LocationCode` column — if that isn't your code, add the
      column. (Training files also carry the configured partner code; see
      [this warning](./converters.md#-this-is-a-single-organization-tool).)

---

## Want more detail?

| For | Read |
|---|---|
| Every screen of the web app, and every count and tab explained | [web-app-guide.md](./web-app-guide.md) |
| Which columns each converter reads | [csv-reference.md](./csv-reference.md) |
| What the tool changes or fills in, and why | [converters.md](./converters.md) |
| A specific error message | [troubleshooting.md](./troubleshooting.md) |
| Installing and running the app | [getting-started.md](./getting-started.md) |
