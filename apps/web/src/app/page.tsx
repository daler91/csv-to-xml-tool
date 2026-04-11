import Link from "next/link";
import { CONVERTER_TYPES } from "@/lib/converter-types";

/**
 * Homepage for unauthenticated users.
 *
 * Resolves UX_REVIEW.md §2.1. The old landing page was one
 * paragraph + two buttons and told partners nothing about what to
 * bring, what the three converter types mean, or where samples
 * live. The rebuild has three sections — hero, "What this
 * converts", and "How it works" — so a partner arriving from a
 * shared link can evaluate the tool without signing up first.
 */
export default function Home() {
  return (
    <main className="max-w-4xl mx-auto px-4 py-12">
      {/* Hero */}
      <section className="text-center mb-16">
        <h1 className="text-3xl sm:text-4xl font-bold mb-4">
          SBA CSV to XML Converter
        </h1>
        <p className="text-base sm:text-lg text-gray-700 mb-8 max-w-2xl mx-auto leading-relaxed">
          Upload counseling or training CSV exports from Salesforce,
          preview the data, map any mismatched columns, and download
          XSD-compliant XML ready for SBA submission.
        </p>
        <div className="flex flex-col sm:flex-row gap-3 justify-center">
          <Link
            href="/login"
            className="px-6 py-3 bg-blue-600 text-white rounded text-base font-medium hover:bg-blue-700"
          >
            Sign In
          </Link>
          <Link
            href="/signup"
            className="px-6 py-3 border border-gray-300 rounded text-base font-medium hover:bg-gray-50"
          >
            Create Account
          </Link>
        </div>
      </section>

      {/* What this converts */}
      <section className="mb-16">
        <h2 className="text-xl sm:text-2xl font-semibold mb-2 text-center">
          What this converts
        </h2>
        <p className="text-sm text-gray-600 text-center mb-6 max-w-2xl mx-auto">
          Pick the form that matches your CSV export. Each type links
          to a sanitized sample you can download and reference.
        </p>
        <div className="grid gap-4 sm:grid-cols-3">
          {CONVERTER_TYPES.map(({ value, label, description, sample }) => (
            <div
              key={value}
              className="rounded-lg border border-gray-200 bg-white p-5"
            >
              <h3 className="font-semibold text-sm mb-2">{label}</h3>
              <p className="text-sm text-gray-600 leading-relaxed mb-4">
                {description}
              </p>
              <a
                href={sample}
                className="text-sm text-blue-700 underline"
                download
              >
                Download sample CSV
              </a>
            </div>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section className="mb-16">
        <h2 className="text-xl sm:text-2xl font-semibold mb-6 text-center">
          How it works
        </h2>
        <ol className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 max-w-4xl mx-auto">
          {[
            {
              step: 1,
              title: "Upload your CSV",
              body: "Drag and drop a Salesforce export (up to 50MB).",
            },
            {
              step: 2,
              title: "Preview & map",
              body: "We detect column mismatches and suggest matches.",
            },
            {
              step: 3,
              title: "Convert & validate",
              body: "One click runs the converter and validates against the XSD.",
            },
            {
              step: 4,
              title: "Download XML",
              body: "Grab the XSD-compliant XML, plus validation and cleaning reports.",
            },
          ].map(({ step, title, body }) => (
            <li
              key={step}
              className="rounded-lg border border-gray-200 bg-white p-4"
            >
              <div className="flex items-center gap-2 mb-2">
                <span
                  aria-hidden="true"
                  className="flex-shrink-0 w-6 h-6 rounded-full bg-blue-600 text-white text-xs font-semibold flex items-center justify-center"
                >
                  {step}
                </span>
                <h3 className="font-semibold text-sm">{title}</h3>
              </div>
              <p className="text-xs text-gray-600 leading-relaxed">
                {body}
              </p>
            </li>
          ))}
        </ol>
      </section>

      {/* Footer note */}
      <p className="text-xs text-gray-500 text-center">
        Your data stays on SBA infrastructure. Nothing is sent to
        third-party services.
      </p>
    </main>
  );
}
