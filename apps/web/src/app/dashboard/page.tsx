import Link from "next/link";
import { prisma } from "@/lib/prisma";
import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";

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
        <Link
          href="/convert"
          className="px-4 py-2 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700"
        >
          New Conversion
        </Link>
      </div>

      {jobs.length === 0 && page === 1 ? (
        <div className="text-center py-16 text-gray-500">
          <p className="text-lg mb-2">No conversions yet</p>
          <p className="text-sm">
            Upload a CSV file to get started.
          </p>
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

function XsdStatus({ xsdValid }: Readonly<{ xsdValid: boolean | null }>) {
  if (xsdValid === null) return <>-</>;
  if (xsdValid) return <span className="text-green-600">Valid</span>;
  return <span className="text-red-600">Invalid</span>;
}

function StatusBadge({ status }: Readonly<{ status: string }>) {
  const colors: Record<string, string> = {
    uploaded: "bg-gray-100 text-gray-700",
    previewed: "bg-blue-100 text-blue-700",
    mapping: "bg-yellow-100 text-yellow-700",
    converting: "bg-blue-100 text-blue-700",
    complete: "bg-green-100 text-green-700",
    error: "bg-red-100 text-red-700",
    cancelled: "bg-gray-100 text-gray-600",
  };

  return (
    <span
      className={`px-2 py-0.5 rounded text-xs font-medium ${
        colors[status] || "bg-gray-100 text-gray-700"
      }`}
    >
      {status}
    </span>
  );
}
