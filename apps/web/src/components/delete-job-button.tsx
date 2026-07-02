"use client";

/**
 * Delete-a-job control shared by the dashboard rows and the results
 * page. Deleting removes the uploaded CSV and generated XML from disk
 * and the job row itself (the audit trail survives) — so it always
 * confirms first.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";

interface DeleteJobButtonProps {
  jobId: string;
  fileName: string;
  /** "link" renders like the row actions on the dashboard; "button" is a destructive Button. */
  variant?: "link" | "button";
  /** Where to go after a successful delete; omitted = refresh in place. */
  redirectTo?: string;
}

export function DeleteJobButton({
  jobId,
  fileName,
  variant = "link",
  redirectTo,
}: DeleteJobButtonProps) {
  const router = useRouter();
  const toast = useToast();
  const [deleting, setDeleting] = useState(false);

  async function handleDelete() {
    if (
      !window.confirm(
        `Delete "${fileName}" and its converted XML? This removes the files permanently; the audit trail is kept.`
      )
    ) {
      return;
    }
    setDeleting(true);
    try {
      const res = await fetch(`/api/jobs/${jobId}`, { method: "DELETE" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || "Failed to delete job");
      }
      toast.success(`Deleted "${fileName}"`);
      if (redirectTo) {
        router.push(redirectTo);
      }
      router.refresh();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to delete job"
      );
      setDeleting(false);
    }
  }

  if (variant === "button") {
    return (
      <Button
        variant="destructive"
        onClick={handleDelete}
        isLoading={deleting}
      >
        Delete job
      </Button>
    );
  }

  return (
    <button
      onClick={handleDelete}
      disabled={deleting}
      className="text-red-600 hover:underline disabled:opacity-50 disabled:cursor-not-allowed"
    >
      {deleting ? "Deleting…" : "Delete"}
    </button>
  );
}
