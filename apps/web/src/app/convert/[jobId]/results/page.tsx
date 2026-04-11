import { prisma } from "@/lib/prisma";
import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import Link from "next/link";

interface ValidationIssue {
  record_id: string;
  severity: string;
  category: string;
  field_name: string;
  message: string;
}

interface CleaningDiffEntry {
  row: number;
  record_id: string;
  field: string;
  original: string;
  cleaned: string;
  cleaning_type: string;
}

export default async function ResultsPage({
  params,
  searchParams,
}: Readonly<{
  params: Promise<{ jobId: string }>;
  searchParams: Promise<{ tab?: string; filter?: string; showAll?: string }>;
}>) {
  const session = await auth();
  if (!session?.user?.id) redirect("/login");

  const { jobId } = await params;
  const { tab, filter, showAll } = await searchParams;

  const job = await prisma.job.findFirst({
    where: { id: jobId, userId: session.user.id },
  });

  if (!job) redirect("/dashboard");

  if (job.status === "converting") {
    redirect(`/convert/${jobId}/progress`);
  }

  const summary = job.summary as unknown as Record<string, number> | null;
  const issues = (job.issues as unknown as ValidationIssue[]) || [];
  const xsdErrors = (job.xsdErrors as unknown as string[]) || [];
  const cleaningDiffs =
    (job.cleaningDiffs as unknown as CleaningDiffEntry[]) || [];
  const errors = issues.filter((i) => i.severity === "error");
  const warnings = issues.filter((i) => i.severity === "warning");

  // Load previous job for comparison if this is a re-upload
  let comparison: {
    resolved: ValidationIssue[];
    newIssues: ValidationIssue[];
    persistent: ValidationIssue[];
  } | null = null;

  if (job.previousJobId) {
    const previousJob = await prisma.job.findFirst({
      where: { id: job.previousJobId, userId: session.user.id },
    });
    if (previousJob) {
      const prevIssues =
        (previousJob.issues as unknown as ValidationIssue[]) || [];
      comparison = computeComparison(prevIssues, issues);
    }
  }

  // Cleaning diff tab
  if (tab === "diff" && cleaningDiffs.length > 0) {
    return (
      <main className="max-w-6xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold">Cleaning Diff</h1>
            <p className="text-sm text-gray-500">{job.inputFileName}</p>
          </div>
          <Link
            href={`/convert/${jobId}/results`}
            className="px-4 py-2 border border-gray-300 rounded text-sm hover:bg-gray-50"
          >
            Back to Results
          </Link>
        </div>

        <CleaningDiffView
          diffs={cleaningDiffs}
          filter={filter}
          showAll={showAll === "true"}
          jobId={jobId}
        />
      </main>
    );
  }

  return (
    <main className="max-w-6xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Conversion Results</h1>
          <p className="text-sm text-gray-500">{job.inputFileName}</p>
        </div>
        <div className="flex gap-2">
          {job.outputFilePath && (
            <a
              href={`/api/jobs/${jobId}/download`}
              className="px-4 py-2 bg-green-600 text-white rounded text-sm font-medium hover:bg-green-700"
            >
              Download XML
            </a>
          )}
          <Link
            href={`/convert/${jobId}/reupload`}
            className="px-4 py-2 border border-gray-300 rounded text-sm hover:bg-gray-50"
          >
            Re-upload
          </Link>
        </div>
      </div>

      {/* Summary Cards */}
      {summary && (
        <div className="grid grid-cols-4 gap-4 mb-6">
          <SummaryCard label="Total Records" value={summary.total} />
          <SummaryCard
            label="Successful"
            value={summary.successful}
            color="green"
          />
          <SummaryCard label="Errors" value={summary.errors} color="red" />
          <SummaryCard
            label="Warnings"
            value={summary.warnings}
            color="yellow"
          />
        </div>
      )}

      {/* Comparison Summary */}
      {comparison && (
        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="bg-green-50 border border-green-200 rounded p-4">
            <p className="text-sm text-green-700">Resolved</p>
            <p className="text-2xl font-bold text-green-600">
              {comparison.resolved.length}
            </p>
          </div>
          <div className="bg-red-50 border border-red-200 rounded p-4">
            <p className="text-sm text-red-700">New Issues</p>
            <p className="text-2xl font-bold text-red-600">
              {comparison.newIssues.length}
            </p>
          </div>
          <div className="bg-yellow-50 border border-yellow-200 rounded p-4">
            <p className="text-sm text-yellow-700">Persistent</p>
            <p className="text-2xl font-bold text-yellow-600">
              {comparison.persistent.length}
            </p>
          </div>
        </div>
      )}

      {/* XSD Validation */}
      <div className="bg-white border rounded p-4 mb-6">
        <h2 className="font-semibold mb-2">XSD Validation</h2>
        {job.xsdValid === null && (
          <p className="text-sm text-gray-500">Not validated</p>
        )}
        {job.xsdValid === true && (
          <p className="text-sm text-green-600">
            XML is valid against the XSD schema
          </p>
        )}
        {job.xsdValid === false && (
          <div>
            <p className="text-sm text-red-600 mb-2">
              XML failed XSD validation ({xsdErrors.length} errors)
            </p>
            <ul className="text-xs text-red-500 space-y-1 max-h-40 overflow-y-auto">
              {xsdErrors.map((err) => (
                <li key={err} className="font-mono">
                  {err}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Cleaning Diff Link */}
      {cleaningDiffs.length > 0 && (
        <div className="bg-blue-50 border border-blue-200 rounded p-4 mb-6">
          <p className="text-sm text-blue-700">
            Data cleaning made {cleaningDiffs.length} changes.{" "}
            <Link
              href={`/convert/${jobId}/results?tab=diff`}
              className="underline"
            >
              View cleaning diff
            </Link>
          </p>
        </div>
      )}

      {/* Validation Issues */}
      {errors.length > 0 && (
        <div className="mb-6">
          <h2 className="font-semibold mb-2 text-red-700">
            Errors ({errors.length})
          </h2>
          <IssueTable issues={errors} showAll={showAll === "true"} jobId={jobId} />
        </div>
      )}

      {warnings.length > 0 && (
        <div className="mb-6">
          <h2 className="font-semibold mb-2 text-yellow-700">
            Warnings ({warnings.length})
          </h2>
          <IssueTable issues={warnings} showAll={showAll === "true"} jobId={jobId} />
        </div>
      )}

      {issues.length === 0 && (
        <p className="text-sm text-green-600">No validation issues found.</p>
      )}
    </main>
  );
}

function computeComparison(
  prevIssues: ValidationIssue[],
  currIssues: ValidationIssue[]
) {
  const key = (i: ValidationIssue) =>
    `${i.record_id}|${i.field_name}|${i.category}`;

  const prevSet = new Set(prevIssues.map(key));
  const currSet = new Set(currIssues.map(key));

  return {
    resolved: prevIssues.filter((i) => !currSet.has(key(i))),
    newIssues: currIssues.filter((i) => !prevSet.has(key(i))),
    persistent: currIssues.filter((i) => prevSet.has(key(i))),
  };
}

function SummaryCard({
  label,
  value,
  color,
}: Readonly<{
  label: string;
  value: number;
  color?: string;
}>) {
  const colors: Record<string, string> = {
    green: "text-green-600",
    red: "text-red-600",
    yellow: "text-yellow-600",
  };

  return (
    <div className="bg-white border rounded p-4">
      <p className="text-sm text-gray-500">{label}</p>
      <p className={`text-2xl font-bold ${color ? colors[color] : ""}`}>
        {value}
      </p>
    </div>
  );
}

function IssueTable({
  issues,
  showAll,
  jobId,
}: Readonly<{
  issues: ValidationIssue[];
  showAll: boolean;
  jobId: string;
}>) {
  const DISPLAY_LIMIT = 100;
  const displayed = showAll ? issues : issues.slice(0, DISPLAY_LIMIT);

  return (
    <div className="bg-white border rounded overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b bg-gray-50">
            <th scope="col" className="text-left px-3 py-2 font-medium">Record</th>
            <th scope="col" className="text-left px-3 py-2 font-medium">Category</th>
            <th scope="col" className="text-left px-3 py-2 font-medium">Field</th>
            <th scope="col" className="text-left px-3 py-2 font-medium">Message</th>
          </tr>
        </thead>
        <tbody>
          {displayed.map((issue) => (
            <tr key={`${issue.record_id}-${issue.field_name}-${issue.category}`} className="border-b">
              <td className="px-3 py-2 font-mono">{issue.record_id}</td>
              <td className="px-3 py-2">{issue.category}</td>
              <td className="px-3 py-2">{issue.field_name}</td>
              <td className="px-3 py-2">{issue.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!showAll && issues.length > DISPLAY_LIMIT && (
        <div className="p-3">
          <p className="text-xs text-gray-500 mb-1">
            Showing {DISPLAY_LIMIT} of {issues.length} issues
          </p>
          <Link
            href={`/convert/${jobId}/results?showAll=true`}
            className="text-xs text-blue-600 underline"
          >
            Show all
          </Link>
        </div>
      )}
    </div>
  );
}

function CleaningDiffView({
  diffs,
  filter,
  showAll,
  jobId,
}: Readonly<{
  diffs: CleaningDiffEntry[];
  filter?: string;
  showAll: boolean;
  jobId: string;
}>) {
  // Group by cleaning type for summary
  const typeCounts: Record<string, number> = {};
  for (const d of diffs) {
    typeCounts[d.cleaning_type] = (typeCounts[d.cleaning_type] || 0) + 1;
  }
  const types = Object.keys(typeCounts).sort((a, b) => a.localeCompare(b));

  const LABELS: Record<string, string> = {
    format_date: "dates standardized",
    clean_phone: "phones cleaned",
    standardize_state: "states expanded",
    standardize_country: "countries standardized",
    map_gender: "gender values mapped",
    clean_percentage: "percentages cleaned",
    clean_numeric: "numeric values cleaned",
  };

  const summaryParts = types.map(
    (t) => `${typeCounts[t]} ${LABELS[t] || t}`
  );

  const filtered = filter ? diffs.filter((d) => d.cleaning_type === filter) : diffs;
  const displayLimit = 200;
  const displayed = showAll ? filtered : filtered.slice(0, displayLimit);

  return (
    <>
      <div className="bg-white border rounded p-4 mb-6">
        <p className="text-sm text-gray-700">{summaryParts.join(", ")}</p>
      </div>

      {/* Filter */}
      <div className="mb-4 flex items-center gap-2">
        <span className="text-sm text-gray-600">Filter by type:</span>
        <div className="flex gap-1 flex-wrap">
          <Link
            href={`/convert/${jobId}/results?tab=diff`}
            className={`px-2 py-1 text-xs rounded border ${
              filter ? "hover:bg-gray-50" : "bg-blue-100 border-blue-300"
            }`}
          >
            All ({diffs.length})
          </Link>
          {types.map((t) => (
            <Link
              key={t}
              href={`/convert/${jobId}/results?tab=diff&filter=${t}`}
              className={`px-2 py-1 text-xs rounded border ${
                filter === t
                  ? "bg-blue-100 border-blue-300"
                  : "hover:bg-gray-50"
              }`}
            >
              {t} ({typeCounts[t]})
            </Link>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="bg-white border rounded overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b bg-gray-50">
              <th scope="col" className="text-left px-3 py-2 font-medium">Row</th>
              <th scope="col" className="text-left px-3 py-2 font-medium">Record ID</th>
              <th scope="col" className="text-left px-3 py-2 font-medium">Field</th>
              <th scope="col" className="text-left px-3 py-2 font-medium">Original</th>
              <th scope="col" className="text-left px-3 py-2 font-medium">Cleaned</th>
              <th scope="col" className="text-left px-3 py-2 font-medium">Type</th>
            </tr>
          </thead>
          <tbody>
            {displayed.map((d) => (
              <tr key={`${d.row}-${d.record_id}-${d.field}`} className="border-b">
                <td className="px-3 py-2 font-mono">{d.row}</td>
                <td className="px-3 py-2 font-mono">{d.record_id}</td>
                <td className="px-3 py-2">{d.field}</td>
                <td className="px-3 py-2 bg-red-50 text-red-700">
                  {d.original}
                </td>
                <td className="px-3 py-2 bg-green-50 text-green-700">
                  {d.cleaned}
                </td>
                <td className="px-3 py-2 text-gray-500">{d.cleaning_type}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {showAll === false && filtered.length > displayLimit && (
          <div className="p-3">
            <p className="text-xs text-gray-500 mb-1">
              Showing {displayLimit} of {filtered.length} changes
            </p>
            <Link
              href={"/convert/" + jobId + "/results?tab=diff" + (filter ? "&filter=" + filter : "") + "&showAll=true"}
              className="text-xs text-blue-600 underline"
            >
              Show all
            </Link>
          </div>
        )}
      </div>
    </>
  );
}
