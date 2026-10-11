import type { Prisma } from "@prisma/client";
import { prisma } from "@/lib/prisma";

/**
 * Write an audit entry for a change that has already happened.
 *
 * A failed write is logged, not thrown: by the time these are called the
 * mapping is saved or the user is signed in, and failing the request then
 * would report an error for something that succeeded.
 */
export async function recordAudit(entry: {
  userId: string;
  action: string;
  jobId?: string;
  metadata?: Prisma.InputJsonValue;
}): Promise<void> {
  try {
    await prisma.auditEntry.create({ data: entry });
  } catch (error) {
    console.error(`[audit] failed to record ${entry.action}:`, error);
  }
}
