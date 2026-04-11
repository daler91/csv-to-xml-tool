"use client";

import { SessionProvider } from "next-auth/react";
import { ToastProvider } from "./toast";

export function Providers({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <SessionProvider>
      <ToastProvider>{children}</ToastProvider>
    </SessionProvider>
  );
}
