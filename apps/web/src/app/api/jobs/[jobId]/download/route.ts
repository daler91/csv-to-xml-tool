import { NextResponse } from "next/server";
import { readFile } from "node:fs/promises";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { routeError } from "@/lib/api-errors";
import { resolveWithinDataDir } from "@/lib/paths";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ jobId: string }> }
) {
  try {
    const user = await getRequiredUser();
    const { jobId } = await params;

    const job = await prisma.job.findFirst({
      where: { id: jobId, userId: user.id },
    });

    if (!job) {
      return NextResponse.json({ error: "File not found" }, { status: 404 });
    }

    // Distinguish "expired" from "never existed". schema.prisma documents the
    // intent — "The row (and its audit trail) survives; downloads show
    // 'expired'" — but this returned a flat 404 for both, so a user whose file
    // had aged out was told it was missing rather than removed by retention.
    // The results page already renders the expired case; the API now matches.
    if (job.filesPurgedAt) {
      return NextResponse.json(
        {
          error:
            "This file has expired and been removed. Re-run the conversion to generate it again.",
          expired: true,
        },
        { status: 410 }
      );
    }

    if (!job.outputFilePath) {
      return NextResponse.json({ error: "File not found" }, { status: 404 });
    }

    // Validate the file path stays within DATA_DIR to prevent path traversal
    // (shared guard in lib/paths.ts). A path that escapes DATA_DIR or no longer
    // exists throws -> 404.
    let resolvedPath: string;
    try {
      resolvedPath = await resolveWithinDataDir(job.outputFilePath);
    } catch {
      return NextResponse.json({ error: "File not found" }, { status: 404 });
    }

    const fileBuffer = await readFile(/* turbopackIgnore: true */ resolvedPath);
    const fileName = job.inputFileName.replace(".csv", ".xml");

    await prisma.auditEntry.create({
      data: { userId: user.id, jobId, action: "download" },
    });

    return new NextResponse(fileBuffer, {
      headers: {
        "Content-Type": "application/xml",
        "Content-Disposition": `attachment; filename="${fileName}"`,
      },
    });
  } catch (error) {
    return routeError(error, "Download failed");
  }
}
