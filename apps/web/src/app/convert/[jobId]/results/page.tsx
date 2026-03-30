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

export default async function ResultsPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const session = await auth();
  if (!session?.user?.id) redirect("/login");

  const { jobId } = await params;
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
  const errors = issues.filter((i) => i.severity === "error");
  const warnings = issues.filter((i) => i.severity === "warning");

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
            href={`/convert/${jobId}/preview`}
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

      {/* XSD Validation */}
      <div className="bg-white border rounded p-4 mb-6">
        <h2 className="font-semibold mb-2">XSD Validation</h2>
        {job.xsdValid === null ? (
          <p className="text-sm text-gray-500">Not validated</p>
        ) : job.xsdValid ? (
          <p className="text-sm text-green-600">XML is valid against the XSD schema</p>
        ) : (
          <div>
            <p className="text-sm text-red-600 mb-2">
              XML failed XSD validation ({xsdErrors.length} errors)
            </p>
            <ul className="text-xs text-red-500 space-y-1 max-h-40 overflow-y-auto">
              {xsdErrors.map((err, i) => (
                <li key={i} className="font-mono">{err}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Cleaning Diff Link */}
      {job.cleaningDiffs && (job.cleaningDiffs as unknown[]).length > 0 && (
        <div className="bg-blue-50 border border-blue-200 rounded p-4 mb-6">
          <p className="text-sm text-blue-700">
            Data cleaning made {(job.cleaningDiffs as unknown[]).length} changes.{" "}
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
          <IssueTable issues={errors} />
        </div>
      )}

      {warnings.length > 0 && (
        <div className="mb-6">
          <h2 className="font-semibold mb-2 text-yellow-700">
            Warnings ({warnings.length})
          </h2>
          <IssueTable issues={warnings} />
        </div>
      )}

      {issues.length === 0 && (
        <p className="text-sm text-green-600">
          No validation issues found.
        </p>
      )}
    </main>
  );
}

function SummaryCard({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color?: string;
}) {
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

function IssueTable({ issues }: { issues: ValidationIssue[] }) {
  return (
    <div className="bg-white border rounded overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b bg-gray-50">
            <th className="text-left px-3 py-2 font-medium">Record</th>
            <th className="text-left px-3 py-2 font-medium">Category</th>
            <th className="text-left px-3 py-2 font-medium">Field</th>
            <th className="text-left px-3 py-2 font-medium">Message</th>
          </tr>
        </thead>
        <tbody>
          {issues.slice(0, 100).map((issue, i) => (
            <tr key={i} className="border-b">
              <td className="px-3 py-2 font-mono">{issue.record_id}</td>
              <td className="px-3 py-2">{issue.category}</td>
              <td className="px-3 py-2">{issue.field_name}</td>
              <td className="px-3 py-2">{issue.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {issues.length > 100 && (
        <p className="text-xs text-gray-500 p-3">
          Showing 100 of {issues.length} issues
        </p>
      )}
    </div>
  );
}
