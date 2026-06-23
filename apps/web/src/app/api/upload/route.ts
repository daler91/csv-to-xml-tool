import { NextResponse } from "next/server";
import { writeFile, mkdir, rm } from "node:fs/promises";
import path from "node:path";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { rateLimit } from "@/lib/rate-limit";

const DATA_DIR = process.env.DATA_DIR || "/data";

export async function POST(req: Request) {
  try {
    const user = await getRequiredUser();

    const { success, remaining } = await rateLimit(`upload:${user.id}`, 10, 60);
    if (!success) {
      return NextResponse.json(
        { error: "Too many requests" },
        { status: 429, headers: { "X-RateLimit-Remaining": String(remaining) } }
      );
    }

    const formData = await req.formData();
    const file = formData.get("file") as File;
    const converterType = formData.get("converterType") as string;
    const previousJobId = formData.get("previousJobId") as string | null;

    if (!file || !converterType) {
      return NextResponse.json(
        { error: "File and converter type are required" },
        { status: 400 }
      );
    }

    if (!file.name.endsWith(".csv")) {
      return NextResponse.json(
        { error: "Only CSV files are accepted" },
        { status: 400 }
      );
    }

    const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50MB
    if (file.size > MAX_FILE_SIZE) {
      return NextResponse.json(
        { error: "File size exceeds 50MB limit" },
        { status: 413 }
      );
    }

    if (!["counseling", "training", "training-client"].includes(converterType)) {
      return NextResponse.json(
        {
          error:
            "Converter type must be 'counseling', 'training', or 'training-client'",
        },
        { status: 400 }
      );
    }

    // Sanitize filename to prevent path traversal
    const sanitizedFileName = path.basename(file.name).replace(/[^a-zA-Z0-9._-]/g, "_");

    // SEC-2: validate previousJobId ownership before linking, to prevent an
    // IDOR where a user attaches their new job to another user's job id.
    if (previousJobId) {
      const previousJob = await prisma.job.findFirst({
        where: { id: previousJobId, userId: user.id },
        select: { id: true },
      });
      if (!previousJob) {
        return NextResponse.json(
          { error: "Invalid previousJobId" },
          { status: 400 }
        );
      }
    }

    // Create job first to get ID
    const job = await prisma.job.create({
      data: {
        userId: user.id,
        converterType,
        inputFileName: sanitizedFileName,
        inputFilePath: "", // Will update after save
        ...(previousJobId ? { previousJobId } : {}),
      },
    });

    // Save file to volume
    const uploadDir = path.join(DATA_DIR, "uploads", job.id);
    try {
      await mkdir(uploadDir, { recursive: true });
      const filePath = path.join(uploadDir, sanitizedFileName);
      const bytes = await file.arrayBuffer();
      await writeFile(filePath, Buffer.from(bytes));

      // Update job with file path
      await prisma.job.update({
        where: { id: job.id },
        data: { inputFilePath: filePath },
      });
    } catch (saveError) {
      // DATA-1: compensating cleanup so a failed save can't leave an orphaned
      // job row (with an empty inputFilePath) behind. No child AuditEntry exists
      // yet here — it is created only after a successful update — so deleting
      // the job is safe.
      await prisma.job.delete({ where: { id: job.id } }).catch(() => {});
      await rm(uploadDir, { recursive: true, force: true }).catch(() => {});
      throw saveError;
    }

    // Create audit entry
    await prisma.auditEntry.create({
      data: {
        userId: user.id,
        jobId: job.id,
        action: "upload",
        metadata: { fileName: file.name, fileSize: file.size },
      },
    });

    return NextResponse.json({ jobId: job.id }, { status: 201 });
  } catch (error) {
    if (error instanceof Error && error.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    console.error("Upload error:", error);
    return NextResponse.json(
      { error: "Upload failed" },
      { status: 500 }
    );
  }
}
