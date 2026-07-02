import { NextResponse } from "next/server";
import { randomUUID } from "node:crypto";
import { prisma } from "@/lib/prisma";
import { getRequiredUser } from "@/lib/session";
import { rateLimit } from "@/lib/rate-limit";
import { workerFetch } from "@/lib/worker-client";
import { MAX_UPLOAD_BYTES } from "@/lib/limits";

// Mirrors the worker's schema_type contract: training-client shares the
// counseling XSD, so the UI only exposes counseling/training, but all
// three are accepted for future callers.
const SCHEMA_TYPES = new Set(["counseling", "training", "training-client"]);

interface ValidateXsdResponse {
  is_valid: boolean;
  errors: string[];
  error_count: number;
}

/**
 * Standalone pre-submission check: validate an existing XML file
 * (hand-edited, legacy, or from another tool) against the SBA Nexus
 * XSDs without creating a conversion job. Proxies to the worker's
 * content-based /validate-xsd endpoint.
 */
export async function POST(req: Request) {
  try {
    const user = await getRequiredUser();

    const { success, remaining } = await rateLimit(
      `validate-xml:${user.id}`,
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
        { error: "Unknown schema type" },
        { status: 400 }
      );
    }

    const xmlContent = await file.text();
    const result = await workerFetch<ValidateXsdResponse>("/validate-xsd", {
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
        action: "xml_validated",
        metadata: {
          fileName: file.name,
          schemaType,
          isValid: result.is_valid,
          errorCount: result.error_count,
        },
      },
    });

    return NextResponse.json(result);
  } catch (error) {
    if (error instanceof Error && error.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    console.error("Validate XML error:", error);
    return NextResponse.json(
      { error: "Validation failed — the validation service may be busy. Try again in a moment." },
      { status: 502 }
    );
  }
}
