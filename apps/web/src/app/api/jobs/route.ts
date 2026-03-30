import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";

export async function GET() {
  try {
    const user = await getRequiredUser();

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
  } catch {
    return NextResponse.json({ error: "Failed to fetch jobs" }, { status: 500 });
  }
}
