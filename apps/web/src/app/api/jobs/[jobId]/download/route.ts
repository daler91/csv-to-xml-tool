import { NextResponse } from "next/server";
import { readFile, realpath } from "node:fs/promises";
import path from "node:path";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";

const DATA_DIR = process.env.DATA_DIR || "/data";

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

    if (!job?.outputFilePath) {
      return NextResponse.json({ error: "File not found" }, { status: 404 });
    }

    // Validate the file path stays within DATA_DIR to prevent path traversal
    const resolvedPath = await realpath(job.outputFilePath);
    const resolvedDataDir = await realpath(DATA_DIR);
    if (!resolvedPath.startsWith(resolvedDataDir + path.sep)) {
      return NextResponse.json({ error: "File not found" }, { status: 404 });
    }

    const fileBuffer = await readFile(resolvedPath);
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
  } catch {
    return NextResponse.json({ error: "Download failed" }, { status: 500 });
  }
}
