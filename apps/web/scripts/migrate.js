// Simple SQL migration script - creates tables if they don't exist.
// Runs on container startup before the Next.js server.
// No prisma CLI needed - just raw SQL via the pg driver in @prisma/client.

const { PrismaClient } = require("@prisma/client");

async function migrate() {
  const prisma = new PrismaClient();
  try {
    // Test connection
    await prisma.$queryRaw`SELECT 1`;
    console.log("Database connected");

    // Create tables if they don't exist
    await prisma.$executeRawUnsafe(`
      CREATE TABLE IF NOT EXISTS "User" (
        "id" TEXT NOT NULL,
        "email" TEXT NOT NULL,
        "name" TEXT,
        "passwordHash" TEXT NOT NULL,
        "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
        "updatedAt" TIMESTAMP(3) NOT NULL,
        CONSTRAINT "User_pkey" PRIMARY KEY ("id")
      );

      CREATE UNIQUE INDEX IF NOT EXISTS "User_email_key" ON "User"("email");

      CREATE TABLE IF NOT EXISTS "Job" (
        "id" TEXT NOT NULL,
        "userId" TEXT NOT NULL,
        "converterType" TEXT NOT NULL,
        "status" TEXT NOT NULL DEFAULT 'uploaded',
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
        "updatedAt" TIMESTAMP(3) NOT NULL,
        "completedAt" TIMESTAMP(3),
        CONSTRAINT "Job_pkey" PRIMARY KEY ("id")
      );

      CREATE INDEX IF NOT EXISTS "Job_userId_createdAt_idx" ON "Job"("userId", "createdAt" DESC);

      CREATE TABLE IF NOT EXISTS "AuditEntry" (
        "id" TEXT NOT NULL,
        "userId" TEXT NOT NULL,
        "jobId" TEXT,
        "action" TEXT NOT NULL,
        "metadata" JSONB,
        "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT "AuditEntry_pkey" PRIMARY KEY ("id")
      );

      CREATE INDEX IF NOT EXISTS "AuditEntry_userId_createdAt_idx" ON "AuditEntry"("userId", "createdAt" DESC);
      CREATE INDEX IF NOT EXISTS "AuditEntry_action_idx" ON "AuditEntry"("action");

      -- Foreign keys (idempotent via DO block)
      DO $$ BEGIN
        ALTER TABLE "Job" ADD CONSTRAINT "Job_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
      EXCEPTION WHEN duplicate_object THEN NULL; END $$;

      DO $$ BEGIN
        ALTER TABLE "Job" ADD CONSTRAINT "Job_previousJobId_fkey" FOREIGN KEY ("previousJobId") REFERENCES "Job"("id") ON DELETE SET NULL ON UPDATE CASCADE;
      EXCEPTION WHEN duplicate_object THEN NULL; END $$;

      DO $$ BEGIN
        ALTER TABLE "AuditEntry" ADD CONSTRAINT "AuditEntry_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
      EXCEPTION WHEN duplicate_object THEN NULL; END $$;

      DO $$ BEGIN
        ALTER TABLE "AuditEntry" ADD CONSTRAINT "AuditEntry_jobId_fkey" FOREIGN KEY ("jobId") REFERENCES "Job"("id") ON DELETE SET NULL ON UPDATE CASCADE;
      EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    `);

    console.log("Migration complete - all tables ready");
  } catch (err) {
    console.error("Migration failed:", err.message);
  } finally {
    await prisma.$disconnect();
  }
}

migrate();
