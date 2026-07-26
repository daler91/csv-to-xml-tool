import { NextResponse } from "next/server";

/**
 * Shared handling for the "not signed in" case in API routes.
 *
 * `getRequiredUser()` signals a missing session by throwing, and most routes
 * wrapped their whole handler in a bare `catch { ... 500 }` — so an expired
 * session produced "Something went wrong on our side" instead of a 401. Only 5
 * of 13 authenticated handlers translated it, each with its own copy of a
 * string comparison against the error message. `upload-errors.ts` maps 401/403
 * to "Your session expired. Please sign in again", a message the app could
 * therefore almost never show.
 */
export class UnauthorizedError extends Error {
  constructor() {
    // The message is load-bearing: routes not yet migrated to this class still
    // compare `error.message === "Unauthorized"`.
    super("Unauthorized");
    this.name = "UnauthorizedError";
  }
}

export function isUnauthorized(error: unknown): boolean {
  return (
    error instanceof UnauthorizedError ||
    (error instanceof Error && error.message === "Unauthorized")
  );
}

/**
 * Turn a caught route error into a response.
 *
 * Returns 401 for a missing session, otherwise the caller's fallback. Use as
 * the single statement in a route's `catch` block:
 *
 *   } catch (error) {
 *     return routeError(error, "Failed to fetch jobs");
 *   }
 */
export function routeError(
  error: unknown,
  fallbackMessage: string,
  fallbackStatus = 500
): NextResponse {
  if (isUnauthorized(error)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  return NextResponse.json(
    { error: fallbackMessage },
    { status: fallbackStatus }
  );
}
