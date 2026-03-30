import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";

export async function GET(req: Request) {
  try {
    const user = await getRequiredUser();
    const url = new URL(req.url);
    const page = parseInt(url.searchParams.get("page") || "1");
    const pageSize = parseInt(url.searchParams.get("pageSize") || "50");
    const action = url.searchParams.get("action");
    const format = url.searchParams.get("format");

    const where: Record<string, unknown> = { userId: user.id };
    if (action) where.action = action;

    const [entries, total] = await Promise.all([
      prisma.auditEntry.findMany({
        where,
        include: { job: { select: { inputFileName: true, converterType: true } } },
        orderBy: { createdAt: "desc" },
        skip: (page - 1) * pageSize,
        take: pageSize,
      }),
      prisma.auditEntry.count({ where }),
    ]);

    // CSV export
    if (format === "csv") {
      const allEntries = await prisma.auditEntry.findMany({
        where,
        include: { job: { select: { inputFileName: true, converterType: true } } },
        orderBy: { createdAt: "desc" },
      });

      const csvRows = [
        "Date,Action,File,Type,Details",
        ...allEntries.map((e) => {
          const meta = e.metadata as Record<string, unknown> | null;
          return [
            new Date(e.createdAt).toISOString(),
            e.action,
            e.job?.inputFileName || "",
            e.job?.converterType || "",
            meta ? JSON.stringify(meta) : "",
          ]
            .map((v) => `"${String(v).replace(/"/g, '""')}"`)
            .join(",");
        }),
      ].join("\n");

      return new NextResponse(csvRows, {
        headers: {
          "Content-Type": "text/csv",
          "Content-Disposition": 'attachment; filename="audit-trail.csv"',
        },
      });
    }

    return NextResponse.json({
      entries,
      total,
      page,
      pageSize,
      totalPages: Math.ceil(total / pageSize),
    });
  } catch {
    return NextResponse.json(
      { error: "Failed to fetch audit trail" },
      { status: 500 }
    );
  }
}
