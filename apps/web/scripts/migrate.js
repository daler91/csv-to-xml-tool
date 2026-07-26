// Creates database tables on startup. Each statement runs separately
// because Prisma doesn't support multiple statements in one call.
//
// IMPORTANT: this script — not `prisma db push` — is what the deployed
// container runs (Dockerfile CMD), so every change to prisma/schema.prisma
// MUST be mirrored here as an idempotent statement (ADD COLUMN IF NOT
// EXISTS / CREATE TABLE IF NOT EXISTS), or production boots against a
// database missing the new columns and every query on that model fails
// with P2022.

const { PrismaClient } = require("@prisma/client");

const statements = [
  `CREATE TABLE IF NOT EXISTS "User" (
    "id" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "name" TEXT,
    "passwordHash" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "User_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "User_email_key" ON "User"("email")`,
  // SEC-3: normalize existing emails (trim + lowercase). Collision-safe — a row whose
  // normalized form already belongs to another user is left untouched for manual cleanup
  // so this never aborts the boot migration on the unique index.
  `UPDATE "User" u SET "email" = LOWER(TRIM("email"))
    WHERE "email" <> LOWER(TRIM("email"))
      AND NOT EXISTS (
        SELECT 1 FROM "User" v
        WHERE v."email" = LOWER(TRIM(u."email")) AND v."id" <> u."id"
      )`,
  // DATA-2: the JobStatus enum type must exist before the Job table references it.
  `DO $$ BEGIN
    CREATE TYPE "JobStatus" AS ENUM ('uploaded', 'previewed', 'mapping', 'queued', 'converting', 'complete', 'error', 'cancelled');
  EXCEPTION WHEN duplicate_object THEN NULL; END $$`,
  `CREATE TABLE IF NOT EXISTS "Job" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "converterType" TEXT NOT NULL,
    "status" "JobStatus" NOT NULL DEFAULT 'uploaded',
    "inputFileName" TEXT NOT NULL,
    "inputFilePath" TEXT NOT NULL,
    "outputFilePath" TEXT,
    "totalRows" INTEGER,
    "processedRows" INTEGER NOT NULL DEFAULT 0,
    "columnMapping" JSONB,
    "summary" JSONB,
    "issues" JSONB,
    "cleaningDiffs" JSONB,
    "xsdValid" BOOLEAN,
    "xsdErrors" JSONB,
    "previousJobId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "completedAt" TIMESTAMP(3),
    CONSTRAINT "Job_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE INDEX IF NOT EXISTS "Job_userId_createdAt_idx" ON "Job"("userId", "createdAt" DESC)`,
  // DATA-2: convert a pre-existing TEXT status column to the enum. One-time and re-run-safe —
  // the data_type='text' guard makes it a no-op once the column is already the enum.
  `DO $$ BEGIN
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_name = 'Job' AND column_name = 'status' AND data_type = 'text'
    ) THEN
      ALTER TABLE "Job" ALTER COLUMN "status" DROP DEFAULT;
      ALTER TABLE "Job" ALTER COLUMN "status" TYPE "JobStatus" USING "status"::"JobStatus";
      ALTER TABLE "Job" ALTER COLUMN "status" SET DEFAULT 'uploaded';
    END IF;
  END $$`,
  `CREATE TABLE IF NOT EXISTS "AuditEntry" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "jobId" TEXT,
    "action" TEXT NOT NULL,
    "metadata" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "AuditEntry_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE INDEX IF NOT EXISTS "AuditEntry_userId_createdAt_idx" ON "AuditEntry"("userId", "createdAt" DESC)`,
  `CREATE INDEX IF NOT EXISTS "AuditEntry_action_idx" ON "AuditEntry"("action")`,
  `DO $$ BEGIN ALTER TABLE "Job" ADD CONSTRAINT "Job_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$`,
  `DO $$ BEGIN ALTER TABLE "Job" ADD CONSTRAINT "Job_previousJobId_fkey" FOREIGN KEY ("previousJobId") REFERENCES "Job"("id") ON DELETE SET NULL ON UPDATE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$`,
  `DO $$ BEGIN ALTER TABLE "AuditEntry" ADD CONSTRAINT "AuditEntry_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$`,
  `DO $$ BEGIN ALTER TABLE "AuditEntry" ADD CONSTRAINT "AuditEntry_jobId_fkey" FOREIGN KEY ("jobId") REFERENCES "Job"("id") ON DELETE SET NULL ON UPDATE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$`,
  // Retention purge (PR #103): records when the sweep removed this job's files.
  `ALTER TABLE "Job" ADD COLUMN IF NOT EXISTS "filesPurgedAt" TIMESTAMP(3)`,
  // Saved column-mapping templates (PR #103).
  `CREATE TABLE IF NOT EXISTS "MappingTemplate" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "converterType" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "mapping" JSONB NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "MappingTemplate_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "MappingTemplate_userId_converterType_name_key" ON "MappingTemplate"("userId", "converterType", "name")`,
  `CREATE INDEX IF NOT EXISTS "MappingTemplate_userId_converterType_idx" ON "MappingTemplate"("userId", "converterType")`,
  `DO $$ BEGIN ALTER TABLE "MappingTemplate" ADD CONSTRAINT "MappingTemplate_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$`,
];

async function migrate() {
  const prisma = new PrismaClient();
  try {
    await prisma.$queryRaw`SELECT 1`;
    console.log("Database connected");

    for (const sql of statements) {
      await prisma.$executeRawUnsafe(sql);
    }

    console.log("Migration complete - all tables ready");
  } catch (err) {
    // Must exit non-zero. This used to log and fall through, and the Dockerfile
    // CMD chained with `;`, so a failed migration still started the server: the
    // app came up against a half-migrated database and every query failed at
    // request time with P2022 instead of the container failing at boot.
    console.error("Migration failed:", err.message);
    process.exitCode = 1;
  } finally {
    await prisma.$disconnect();
  }
}

// Catch anything thrown outside the try (e.g. new PrismaClient()) rather than
// leaving an unhandled rejection, which would also exit 0 on older Node.
migrate().catch((err) => {
  console.error("Migration failed to run:", err.message);
  process.exitCode = 1;
});
