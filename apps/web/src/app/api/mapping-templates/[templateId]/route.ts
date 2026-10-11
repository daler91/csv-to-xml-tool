import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { recordAudit } from "@/lib/audit";

export async function DELETE(
  _req: Request,
  { params }: { params: Promise<{ templateId: string }> }
) {
  try {
    const user = await getRequiredUser();
    const { templateId } = await params;

    // Read first for the audit entry's name; the delete stays scoped below.
    const template = await prisma.mappingTemplate.findFirst({
      where: { id: templateId, userId: user.id },
      select: { name: true, converterType: true },
    });

    // deleteMany so the userId scope is part of the delete itself —
    // a foreign template id deletes nothing instead of throwing.
    const deleted = await prisma.mappingTemplate.deleteMany({
      where: { id: templateId, userId: user.id },
    });

    if (deleted.count === 0) {
      return NextResponse.json(
        { error: "Template not found" },
        { status: 404 }
      );
    }

    await recordAudit({
      userId: user.id,
      action: "mapping_template_deleted",
      metadata: { name: template?.name ?? null, converterType: template?.converterType ?? null },
    });

    return NextResponse.json({ deleted: true });
  } catch (error) {
    if (error instanceof Error && error.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    console.error("Delete mapping template error:", error);
    return NextResponse.json(
      { error: "Failed to delete mapping template" },
      { status: 500 }
    );
  }
}
