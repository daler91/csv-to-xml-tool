import Link from "next/link";
import { CONVERTER_TYPES } from "@/lib/converter-types";

/**
 * Help page.
 *
 * Resolves UX_REVIEW.md §1.3. The app had no in-product help
 * surface — partners with questions had nowhere to go inside the
 * web UI, and the repo README only documents the Python CLI.
 *
 * This page is intentionally copy-heavy and self-contained. Each
 * section has a stable id so the mapping page, results page, and
 * future contextual "?" buttons can deep-link into the right spot.
 */
export default function HelpPage() {
  return (
    <main className="max-w-3xl mx-auto px-4 py-10">
      <h1 className="text-3xl font-bold mb-2">Help</h1>
      <p className="text-sm text-gray-600 mb-8">
        How to use the CSV to XML converter, common errors, and
        who to contact if something goes wrong.
      </p>

      <TableOfContents
        sections={[
          { id: "overview", label: "What this tool does" },
          { id: "converter-types", label: "Converter types" },
          { id: "upload", label: "Uploading a CSV" },
          { id: "mapping", label: "Reading the mapping page" },
          { id: "results", label: "Reading the results page" },
          { id: "cancel", label: "Cancelling a conversion" },
          { id: "errors", label: "Common errors" },
          { id: "support", label: "Getting help" },
        ]}
      />

      <Section id="overview" title="What this tool does">
        <p>
          This tool takes a counseling or training
          CSV export from Salesforce and produces an XSD-compliant XML
          file ready for submission to the SBA. Along the way it:
        </p>
        <ul className="list-disc pl-5 space-y-1">
          <li>
            Previews the CSV so you can confirm the data before the
            conversion runs.
          </li>
          <li>
            Detects mismatched column names and suggests matches so you
            can fix them without editing the CSV.
          </li>
          <li>
            Cleans dates, phone numbers, state/country names, and other
            common issues automatically.
          </li>
          <li>
            Validates the generated XML against the SBA schema and
            surfaces any remaining problems.
          </li>
          <li>
            Tracks every conversion in your account history so you can
            compare before/after when you re-upload a fixed file.
          </li>
        </ul>
      </Section>

      <Section id="converter-types" title="Converter types">
        <p>
          Pick the converter that matches your data. Each one expects a
          different CSV shape; picking the wrong one will result in
          every column being reported as &quot;missing&quot; on the
          preview page.
        </p>
        <ul className="space-y-3">
          {CONVERTER_TYPES.map((t) => (
            <li key={t.value} className="border rounded p-4 bg-white">
              <p className="font-semibold text-sm">{t.label}</p>
              <p className="text-sm text-gray-700 mt-1">
                {t.description}
              </p>
              <a
                href={t.sample}
                download
                className="inline-block mt-2 text-sm text-blue-700 underline"
              >
                Download sample CSV
              </a>
            </li>
          ))}
        </ul>
      </Section>

      <Section id="upload" title="Uploading a CSV">
        <ol className="list-decimal pl-5 space-y-2">
          <li>
            Sign in and click <strong>New Conversion</strong> from the
            dashboard.
          </li>
          <li>Pick a converter type.</li>
          <li>
            Drag and drop your CSV into the upload area, or click it to
            browse. Files must be <code>.csv</code> and up to 50MB.
          </li>
          <li>
            Click <strong>Upload &amp; Preview</strong>. The CSV is
            uploaded, parsed, and you&apos;re sent to the preview
            screen.
          </li>
        </ol>
      </Section>

      <Section id="mapping" title="Reading the mapping page">
        <p>
          The mapping page appears when your CSV has columns with
          different names than the SBA schema expects. It shows every
          expected field, its requirement level, and lets you point it
          at one of your CSV columns.
        </p>
        <p className="font-semibold">Badge meanings:</p>
        <ul className="space-y-2">
          <li>
            <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-semibold bg-red-100 text-red-700 border border-red-200 mr-2">
              Required
            </span>
            Must be present in the CSV (or mapped from another column)
            for the conversion to produce valid XML.
          </li>
          <li>
            <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-700 border border-amber-200 mr-2">
              Conditional
            </span>
            Only required when a related field has a certain value.
            Each conditional field shows the exact rule ("When
            required: Required when Veteran Status indicates military
            service").
          </li>
          <li>
            <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-semibold bg-gray-100 text-gray-500 border border-gray-200 mr-2">
              Optional
            </span>
            Nice to have but not needed for validation.
          </li>
          <li>
            <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-semibold bg-green-100 text-green-700 border border-green-200 mr-2">
              Auto-matched
            </span>
            Already found in your CSV with the expected name — no
            action needed.
          </li>
        </ul>
        <p>
          Use <strong>Apply All Suggestions</strong> to accept every
          fuzzy-matched column in one click, then <strong>Save Mapping
          &amp; Continue</strong>.
        </p>
      </Section>

      <Section id="results" title="Reading the results page">
        <p>The results page has four sections:</p>
        <ul className="list-disc pl-5 space-y-2">
          <li>
            <strong>Summary cards</strong> — Total records, Successful,
            Errors, Warnings. Each has an icon matching the color.
          </li>
          <li>
            <strong>XSD Validation</strong> — Whether the generated
            XML passed schema validation. Errors are listed inline.
          </li>
          <li>
            <strong>Cleaning diff</strong> — A count of the
            automatic fixes the tool made (dates standardized, phones
            cleaned, states expanded, etc.). Click the link to see
            each change, filtered by type.
          </li>
          <li>
            <strong>Errors &amp; Warnings tables</strong> — Per-record
            issues with the field name, category, and a description
            of what went wrong.
          </li>
        </ul>
        <p>
          Click <strong>Download XML</strong> to grab the generated
          file, or <strong>Re-upload</strong> to upload a fixed CSV
          and compare it against the current conversion.
        </p>
      </Section>

      <Section id="cancel" title="Cancelling a conversion">
        <p>
          While a conversion is running, the progress page shows a
          <strong> Cancel conversion </strong> button. Clicking it
          immediately flips the job to cancelled state and returns
          you to the dashboard. The worker stops at its next
          checkpoint; any partial output is discarded.
        </p>
      </Section>

      <Section id="errors" title="Common errors">
        <dl className="space-y-4">
          <div>
            <dt className="font-semibold">
              &quot;This file is larger than 50MB&quot;
            </dt>
            <dd className="text-gray-700">
              The upload is capped at 50MB. Split the CSV into smaller
              batches, or remove unused columns with Excel or
              Salesforce&apos;s export filters.
            </dd>
          </div>
          <div>
            <dt className="font-semibold">
              &quot;That file isn&apos;t a CSV&quot;
            </dt>
            <dd className="text-gray-700">
              The file extension must be <code>.csv</code>. Export
              from Excel via{" "}
              <em>File → Save As → CSV (Comma delimited)</em>. Don&apos;t
              upload <code>.xlsx</code>.
            </dd>
          </div>
          <div>
            <dt className="font-semibold">
              &quot;You&apos;ve uploaded several files in a short
              window&quot;
            </dt>
            <dd className="text-gray-700">
              There&apos;s a rate limit of 10 uploads per minute per
              user to prevent abuse. Wait about a minute and try
              again.
            </dd>
          </div>
          <div>
            <dt className="font-semibold">Preview fails to load</dt>
            <dd className="text-gray-700">
              The CSV may be malformed. Open it in a text editor or
              Excel and confirm the first row has column headers and
              every line has the same number of commas. Click{" "}
              <strong>Try again</strong> if the server may have been
              busy.
            </dd>
          </div>
          <div>
            <dt className="font-semibold">
              XSD validation fails after a successful conversion
            </dt>
            <dd className="text-gray-700">
              The cleaning pass couldn&apos;t automatically fix
              everything. Open the errors list on the results page,
              correct the rows in your CSV, and use{" "}
              <strong>Re-upload</strong> to compare the two.
            </dd>
          </div>
        </dl>
      </Section>

      <Section id="support" title="Getting help">
        <p>
          If you hit a wall, the fastest paths are:
        </p>
        <ul className="list-disc pl-5 space-y-1">
          <li>
            Review the{" "}
            <a
              href="https://github.com/daler91/csv-to-xml-tool/blob/master/UX_REVIEW.md"
              className="text-blue-700 underline"
              target="_blank"
              rel="noreferrer"
            >
              UX review
            </a>{" "}
            and{" "}
            <a
              href="https://github.com/daler91/csv-to-xml-tool/blob/master/TECHNICAL_DEBT.md"
              className="text-blue-700 underline"
              target="_blank"
              rel="noreferrer"
            >
              technical debt register
            </a>{" "}
            for known issues.
          </li>
          <li>
            File an issue at the{" "}
            <a
              href="https://github.com/daler91/csv-to-xml-tool/issues"
              className="text-blue-700 underline"
              target="_blank"
              rel="noreferrer"
            >
              project repository
            </a>
            .
          </li>
          <li>
            For anything involving client data, contact your SBA
            program coordinator instead of posting it publicly.
          </li>
        </ul>
      </Section>

      <div className="mt-10 pt-6 border-t text-center">
        <Link
          href="/dashboard"
          className="text-sm text-blue-700 underline"
        >
          Back to dashboard
        </Link>
      </div>
    </main>
  );
}

function TableOfContents({
  sections,
}: Readonly<{ sections: Array<{ id: string; label: string }> }>) {
  return (
    <nav aria-label="Page sections" className="mb-8 p-4 bg-gray-50 border rounded">
      <p className="text-xs font-semibold text-gray-600 uppercase mb-2">
        On this page
      </p>
      <ul className="grid sm:grid-cols-2 gap-x-4 gap-y-1 text-sm">
        {sections.map(({ id, label }) => (
          <li key={id}>
            <a href={`#${id}`} className="text-blue-700 hover:underline">
              {label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function Section({
  id,
  title,
  children,
}: Readonly<{ id: string; title: string; children: React.ReactNode }>) {
  return (
    <section id={id} className="mb-10 scroll-mt-16">
      <h2 className="text-xl font-semibold mb-3">
        <a href={`#${id}`} className="no-underline hover:underline">
          {title}
        </a>
      </h2>
      <div className="text-sm text-gray-800 space-y-3 leading-relaxed">
        {children}
      </div>
    </section>
  );
}
