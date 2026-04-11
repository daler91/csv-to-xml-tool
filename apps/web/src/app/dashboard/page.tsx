import Link from "next/link";
import { prisma } from "@/lib/prisma";
import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { StatusIcon } from "@/components/status-icon";
import { StatusBadge } from "@/components/ui/status-badge";
import { buttonClasses } from "@/components/ui/button-classes";

const PAGE_SIZE = 20;

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ page?: string }>;
}) {
  const session = await auth();
  if (!session?.user?.id) redirect("/login");

  const { page: pageParam } = await searchParams;
  const page = Math.max(1, parseInt(pageParam || "1", 10) || 1);
  const skip = (page - 1) * PAGE_SIZE;

  const [jobs, totalCount] = await Promise.all([
    prisma.job.findMany({
      where: { userId: session.user.id },
      orderBy: { createdAt: "desc" },
      skip,
      take: PAGE_SIZE,
    }),
    prisma.job.count({ where: { userId: session.user.id } }),
  ]);

  const totalPages = Math.ceil(totalCount / PAGE_SIZE);

  return (
    <main className="max-w-6xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <Link href="/convert" className={buttonClasses()}>
          New Conversion
        </Link>
      </div>

      {jobs.length === 0 && page === 1 ? (
        <div className="text-center py-16 bg-white border rounded-lg">
          <h2 className="text-xl font-semibold mb-2">No conversions yet</h2>
          <p className="text-sm text-gray-600 mb-6 max-w-md mx-auto">
            Start your first conversion by uploading a CSV export.
            Not sure what to upload? Grab a sample below.
          </p>
          <Link
            href="/convert"
            className={`${buttonClasses()} mb-8`}
          >
            Start a new conversion
          </Link>
          <div className="grid gap-3 sm:grid-cols-3 max-w-3xl mx-auto px-4 text-left">
            <SampleLink
              href="/samples/counseling-sample.csv"
              label="Counseling sample"
              description="Form 641, individual sessions"
            />
            <SampleLink
              href="/samples/training-sample.csv"
              label="Training sample"
              description="Form 888, aggregated events"
            />
            <SampleLink
              href="/samples/training-client-sample.csv"
              label="Training Client sample"
              description="Form 641, per attendee"
            />
          </div>
        </div>
      ) : (
        <>
          <div className="bg-white rounded border overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-gray-50">
                  <th scope="col" className="text-left px-4 py-3 font-medium">File</th>
                  <th scope="col" className="text-left px-4 py-3 font-medium">Type</th>
                  <th scope="col" className="text-left px-4 py-3 font-medium">Status</th>
                  <th scope="col" className="text-left px-4 py-3 font-medium">Records</th>
                  <th scope="col" className="text-left px-4 py-3 font-medium">XSD</th>
                  <th scope="col" className="text-left px-4 py-3 font-medium">Date</th>
                  <th scope="col" className="text-left px-4 py-3 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => {
                  const summary = job.summary as unknown as Record<string, number> | null;
                  return (
                    <tr key={job.id} className="border-b hover:bg-gray-50">
                      <td className="px-4 py-3 font-mono text-xs">
                        {job.inputFileName}
                      </td>
                      <td className="px-4 py-3 capitalize">{job.converterType}</td>
                      <td className="px-4 py-3">
                        <StatusBadge status={job.status} />
                      </td>
                      <td className="px-4 py-3">
                        {summary
                          ? `${summary.successful}/${summary.total}`
                          : "-"}
                      </td>
                      <td className="px-4 py-3">
                        <XsdStatus xsdValid={job.xsdValid} />
                      </td>
                      <td className="px-4 py-3 text-gray-500">
                        {new Date(job.createdAt).toLocaleDateString()}
                      </td>
                      <td className="px-4 py-3">
                        <Link
                          href={`/convert/${job.id}/results`}
                          className="text-blue-600 hover:underline"
                        >
                          View
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-4">
              <p className="text-sm text-gray-500">
                Showing {skip + 1}-{Math.min(skip + PAGE_SIZE, totalCount)} of {totalCount}
              </p>
              <div className="flex gap-2">
                {page > 1 && (
                  <Link
                    href={`/dashboard?page=${page - 1}`}
                    className="px-3 py-1 border rounded text-sm hover:bg-gray-50"
                  >
                    Previous
                  </Link>
                )}
                {page < totalPages && (
                  <Link
                    href={`/dashboard?page=${page + 1}`}
                    className="px-3 py-1 border rounded text-sm hover:bg-gray-50"
                  >
                    Next
                  </Link>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </main>
  );
}

function SampleLink({
  href,
  label,
  description,
}: Readonly<{ href: string; label: string; description: string }>) {
  return (
    <a
      href={href}
      download
      className="block rounded border border-gray-200 bg-gray-50 p-3 hover:border-blue-400 hover:bg-white"
    >
      <p className="text-sm font-medium text-blue-700 underline mb-1">
        {label}
      </p>
      <p className="text-xs text-gray-600">{description}</p>
    </a>
  );
}

function XsdStatus({ xsdValid }: Readonly<{ xsdValid: boolean | null }>) {
  if (xsdValid === null) return <span className="text-gray-500">—</span>;
  if (xsdValid)
    return (
      <span className="inline-flex items-center gap-1 text-green-700">
        <StatusIcon kind="success" />
        Valid
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 text-red-700">
      <StatusIcon kind="error" />
      Invalid
    </span>
  );
}

