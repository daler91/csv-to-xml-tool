import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { routeError } from "@/lib/api-errors";
import { reapStuckConvertingJobs } from "@/lib/job-reaper";
import { purgeExpiredJobFiles } from "@/lib/retention";

export async function GET() {
  try {
    const user = await getRequiredUser();

    // ARCH-1: lazily fail jobs stuck in "converting" past the deadline so the
    // list reflects reality (a crashed conversion otherwise lingers forever).
    await reapStuckConvertingJobs(user.id);
    // Retention: lazily remove files older than the retention window.
    await purgeExpiredJobFiles(user.id);

    const jobs = await prisma.job.findMany({
      where: { userId: user.id },
      orderBy: { createdAt: "desc" },
      select: {
        id: true,
        converterType: true,
        status: true,
        inputFileName: true,
        totalRows: true,
        summary: true,
        xsdValid: true,
        createdAt: true,
        completedAt: true,
      },
    });

    return NextResponse.json(jobs);
  } catch (error) {
    return routeError(error, "Failed to fetch jobs");
  }
}
