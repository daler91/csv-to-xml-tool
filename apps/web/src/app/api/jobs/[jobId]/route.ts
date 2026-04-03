import { NextResponse } from "next/server";
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

    if (!job) {
      return NextResponse.json({ error: "Job not found" }, { status: 404 });
    }

    return NextResponse.json(job);
  } catch {
    return NextResponse.json({ error: "Failed to fetch job" }, { status: 500 });
  }
}

export async function PATCH(
  req: Request,
  { params }: { params: Promise<{ jobId: string }> }
) {
  try {
    const user = await getRequiredUser();
    const { jobId } = await params;
    const data = await req.json();

    const job = await prisma.job.findFirst({
      where: { id: jobId, userId: user.id },
    });

    if (!job) {
      return NextResponse.json({ error: "Job not found" }, { status: 404 });
    }

    // Whitelist fields that clients are allowed to update
    const allowedFields = ["columnMapping", "status"] as const;
    const sanitizedData: Record<string, unknown> = {};
    for (const key of allowedFields) {
      if (key in data) {
        sanitizedData[key] = data[key];
      }
    }

    if (Object.keys(sanitizedData).length === 0) {
      return NextResponse.json({ error: "No valid fields to update" }, { status: 400 });
    }

    const updated = await prisma.job.update({
      where: { id: jobId },
      data: sanitizedData,
    });

    return NextResponse.json(updated);
  } catch {
    return NextResponse.json({ error: "Failed to update job" }, { status: 500 });
  }
}
