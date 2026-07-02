import { NextResponse } from "next/server";
import { Prisma } from "@prisma/client";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { CONVERTER_TYPES } from "@/lib/converter-types";

const VALID_TYPES = new Set(CONVERTER_TYPES.map((t) => t.value));
const MAX_NAME_LENGTH = 60;
const MAX_MAPPING_ENTRIES = 200;
const MAX_ENTRY_LENGTH = 200;

/**
 * Validates the {csvColumn: xmlField} shape shared with
 * Job.columnMapping. Size caps keep a hostile payload from storing
 * megabytes of JSON per template row.
 */
function sanitizeMapping(value: unknown): Record<string, string> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length === 0 || entries.length > MAX_MAPPING_ENTRIES) {
    return null;
  }
  const mapping: Record<string, string> = {};
  for (const [key, val] of entries) {
    if (
      typeof val !== "string" ||
      key.length === 0 ||
      key.length > MAX_ENTRY_LENGTH ||
      val.length === 0 ||
      val.length > MAX_ENTRY_LENGTH
    ) {
      return null;
    }
    mapping[key] = val;
  }
  return mapping;
}

/**
 * Lists the user's saved templates, optionally filtered by converter
 * type. With ?converterType= it also returns the column mapping of the
 * user's most recent completed job of that type, so the mapping page
 * can offer "reuse your last mapping" on a fresh job.
 */
export async function GET(req: Request) {
  try {
    const user = await getRequiredUser();
    const { searchParams } = new URL(req.url);
    const converterType = searchParams.get("converterType");

    if (converterType && !VALID_TYPES.has(converterType as never)) {
      return NextResponse.json(
        { error: "Unknown converter type" },
        { status: 400 }
      );
    }

    const templates = await prisma.mappingTemplate.findMany({
      where: {
        userId: user.id,
        ...(converterType ? { converterType } : {}),
      },
      orderBy: { updatedAt: "desc" },
      select: {
        id: true,
        name: true,
        converterType: true,
        mapping: true,
        updatedAt: true,
      },
    });

    let lastJobMapping: Record<string, string> | null = null;
    if (converterType) {
      const lastJob = await prisma.job.findFirst({
        where: {
          userId: user.id,
          converterType,
          status: "complete",
          columnMapping: { not: Prisma.AnyNull },
        },
        orderBy: { createdAt: "desc" },
        select: { columnMapping: true },
      });
      const mapping = sanitizeMapping(lastJob?.columnMapping);
      if (mapping) {
        lastJobMapping = mapping;
      }
    }

    return NextResponse.json({ templates, lastJobMapping });
  } catch (error) {
    if (error instanceof Error && error.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    console.error("List mapping templates error:", error);
    return NextResponse.json(
      { error: "Failed to load mapping templates" },
      { status: 500 }
    );
  }
}

/**
 * Saves (or overwrites, by name) a mapping template. Overwrite-on-save
 * keeps the common "save again after tweaking" flow to one click
 * instead of failing on the unique constraint.
 */
export async function POST(req: Request) {
  try {
    const user = await getRequiredUser();
    const body = await req.json().catch(() => null);

    const name =
      typeof body?.name === "string" ? body.name.trim() : "";
    const converterType = body?.converterType;
    const mapping = sanitizeMapping(body?.mapping);

    if (!name || name.length > MAX_NAME_LENGTH) {
      return NextResponse.json(
        { error: `Template name must be 1-${MAX_NAME_LENGTH} characters` },
        { status: 400 }
      );
    }
    if (typeof converterType !== "string" || !VALID_TYPES.has(converterType as never)) {
      return NextResponse.json(
        { error: "Unknown converter type" },
        { status: 400 }
      );
    }
    if (!mapping) {
      return NextResponse.json(
        { error: "Mapping must be a non-empty object of column names" },
        { status: 400 }
      );
    }

    const template = await prisma.mappingTemplate.upsert({
      where: {
        userId_converterType_name: {
          userId: user.id,
          converterType,
          name,
        },
      },
      create: { userId: user.id, converterType, name, mapping },
      update: { mapping },
      select: {
        id: true,
        name: true,
        converterType: true,
        mapping: true,
        updatedAt: true,
      },
    });

    return NextResponse.json({ template }, { status: 201 });
  } catch (error) {
    if (error instanceof Error && error.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    console.error("Save mapping template error:", error);
    return NextResponse.json(
      { error: "Failed to save mapping template" },
      { status: 500 }
    );
  }
}
