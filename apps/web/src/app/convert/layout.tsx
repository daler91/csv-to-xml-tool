import { StepIndicator } from "@/components/ui/step-indicator";

/**
 * Layout for the /convert flow.
 *
 * Mounted here so the StepIndicator wraps both the plain /convert
 * upload page and the /convert/[jobId]/* sub-pages (Preview, Map,
 * Progress, Results, Reupload). The indicator is a client component
 * that derives the active step from usePathname().
 *
 * See UX_REVIEW.md §1.2.
 */
export default function ConvertLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <>
      <StepIndicator />
      {children}
    </>
  );
}
