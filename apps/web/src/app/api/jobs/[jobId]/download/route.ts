import { NextResponse } from "next/server";
import { readFile } from "fs/promises";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";

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

    const fileBuffer = await readFile(job.outputFilePath);
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
