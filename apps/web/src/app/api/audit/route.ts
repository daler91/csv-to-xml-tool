import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";

export const DEFAULT_PAGE_SIZE = 50;
export const MAX_PAGE_SIZE = 200;
// Bounds the CSV export, which used to fetch every row a user had ever
// generated, join a job onto each, and build one string in memory.
export const MAX_EXPORT_ROWS = 10_000;

/**
 * Coerce an untrusted query param to a positive integer within bounds.
 *
 * These were raw `Number.parseInt` calls fed straight to Prisma's skip/take:
 * `?pageSize=abc` produced NaN and `?page=0` a negative skip (both 500s), and
 * `?pageSize=100000000` was accepted as-is.
 */
/**
 * Quote-escape a CSV field and defuse spreadsheet formula injection.
 *
 * Exported audit rows carry user-controlled text (filenames, and metadata that
 * records the raw upload name). A value starting with =, +, -, @ or a
 * control character is executed as a formula when the file is opened in Excel
 * or Sheets, so it is prefixed with an apostrophe to force text.
 */
export function escapeCsvValue(value: unknown): string {
  const text = String(value ?? "");
  const needsGuard = /^[=+\-@\t\r]/.test(text);
  return (needsGuard ? `'${text}` : text).replaceAll('"', '""');
}

function boundedInt(raw: string | null, fallback: number, min: number, max: number): number {
  const parsed = Number.parseInt(raw ?? "", 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(Math.max(parsed, min), max);
}

export async function GET(req: Request) {
  try {
    const user = await getRequiredUser();
    const url = new URL(req.url);
    const page = boundedInt(url.searchParams.get("page"), 1, 1, Number.MAX_SAFE_INTEGER);
    const pageSize = boundedInt(
      url.searchParams.get("pageSize"),
      DEFAULT_PAGE_SIZE,
      1,
      MAX_PAGE_SIZE
    );
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
        // Bounded: this previously materialized every row the user had ever
        // generated into a single in-memory string.
        take: MAX_EXPORT_ROWS,
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
            .map((v) => `"${escapeCsvValue(v)}"`)
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
  } catch (error) {
    if (error instanceof Error && error.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json(
      { error: "Failed to fetch audit trail" },
      { status: 500 }
    );
  }
}
