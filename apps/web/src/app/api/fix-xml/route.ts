import { NextResponse } from "next/server";
import { randomUUID } from "node:crypto";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { rateLimit } from "@/lib/rate-limit";
import { workerFetch } from "@/lib/worker-client";
import { MAX_UPLOAD_BYTES } from "@/lib/limits";
import type { XsdErrorDetail } from "@/types";

// The worker's auto-fix only understands counseling-format XML (Form 641);
// training-client shares that XSD so it's accepted too. Plain "training"
// (Form 888) is rejected by the worker, so it's rejected here as well.
const SCHEMA_TYPES = new Set(["counseling", "training-client"]);

interface FixXmlResponse {
  changed: boolean;
  fixed_xml_content: string;
  is_valid: boolean;
  errors: string[];
  error_count: number;
  error_details: XsdErrorDetail[];
}

/**
 * Attempt an automatic structural fix of an XML file (element reordering
 * to match the schema — never inventing data), then re-validate the fixed
 * content. Companion to /api/validate-xml: same auth, limits, and worker
 * proxying, but against the worker's /fix-xml endpoint (Contract C).
 */
export async function POST(req: Request) {
  try {
    const user = await getRequiredUser();

    const { success, remaining } = await rateLimit(
      `fix-xml:${user.id}`,
      10,
      60
    );
    if (!success) {
      return NextResponse.json(
        { error: "Too many requests" },
        { status: 429, headers: { "X-RateLimit-Remaining": String(remaining) } }
      );
    }

    const formData = await req.formData();
    const file = formData.get("file") as File;
    const schemaType = formData.get("schemaType") as string;

    if (!file || !schemaType) {
      return NextResponse.json(
        { error: "File and schema type are required" },
        { status: 400 }
      );
    }
    if (!file.name.toLowerCase().endsWith(".xml")) {
      return NextResponse.json(
        { error: "Only XML files are accepted" },
        { status: 400 }
      );
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      return NextResponse.json(
        { error: "File size exceeds 50MB limit" },
        { status: 413 }
      );
    }
    if (!SCHEMA_TYPES.has(schemaType)) {
      return NextResponse.json(
        { error: "Auto-fix supports counseling-format XML only" },
        { status: 400 }
      );
    }

    const xmlContent = await file.text();
    const result = await workerFetch<FixXmlResponse>("/fix-xml", {
      method: "POST",
      body: JSON.stringify({
        job_id: `adhoc-${randomUUID()}`,
        xml_content: xmlContent,
        schema_type: schemaType,
      }),
      timeoutMs: 60_000,
    });

    await prisma.auditEntry.create({
      data: {
        userId: user.id,
        action: "xml_autofix",
        metadata: {
          fileName: file.name,
          schemaType,
          changed: result.changed,
          isValid: result.is_valid,
        },
      },
    });

    return NextResponse.json(result);
  } catch (error) {
    if (error instanceof Error && error.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    console.error("Fix XML error:", error);
    return NextResponse.json(
      { error: "Auto-fix failed — the fix service may be busy. Try again in a moment." },
      { status: 502 }
    );
  }
}
