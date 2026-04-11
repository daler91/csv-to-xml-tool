"use client";

import { signIn } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import Link from "next/link";
import { useToast } from "@/components/toast";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

interface PasswordRule {
  label: string;
  test: (pw: string) => boolean;
}

const PASSWORD_RULES: readonly PasswordRule[] = [
  { label: "At least 8 characters", test: (pw) => pw.length >= 8 },
  { label: "One uppercase letter", test: (pw) => /[A-Z]/.test(pw) },
  { label: "One digit", test: (pw) => /\d/.test(pw) },
  {
    label: "One special character",
    test: (pw) => /[^A-Za-z0-9]/.test(pw),
  },
] as const;

export default function SignupPage() {
  const router = useRouter();
  const toast = useToast();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [password, setPassword] = useState("");

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError("");

    const formData = new FormData(e.currentTarget);
    const email = formData.get("email") as string;
    const password = formData.get("password") as string;
    const name = formData.get("name") as string;

    const res = await fetch("/api/auth/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, name }),
    });

    if (!res.ok) {
      const data = await res.json();
      setError(data.error || "Signup failed");
      setLoading(false);
      return;
    }

    // Auto sign-in after successful signup
    const result = await signIn("credentials", {
      email,
      password,
      redirect: false,
    });

    if (result?.error) {
      setError("Account created but sign-in failed. Please log in.");
      setLoading(false);
    } else {
      toast.success("Account created");
      router.push("/dashboard");
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <h1 className="text-2xl font-bold">Create Account</h1>
          <p className="text-gray-500 mt-1">SBA CSV to XML Converter</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && <Alert variant="error">{error}</Alert>}

          <div>
            <label htmlFor="name" className="block text-sm font-medium mb-1">
              Name (optional)
            </label>
            <input
              id="name"
              name="name"
              type="text"
              className="w-full border rounded px-3 py-2 text-sm"
            />
          </div>

          <div>
            <label htmlFor="email" className="block text-sm font-medium mb-1">
              Email
            </label>
            <input
              id="email"
              name="email"
              type="email"
              required
              className="w-full border rounded px-3 py-2 text-sm"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium mb-1">
              Password
            </label>
            <input
              id="password"
              name="password"
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-describedby="password-rules"
              className="w-full border rounded px-3 py-2 text-sm"
            />
            <ul
              id="password-rules"
              aria-label="Password requirements"
              className="mt-2 space-y-1 text-xs"
            >
              {PASSWORD_RULES.map((rule) => {
                const ok = rule.test(password);
                return (
                  <li
                    key={rule.label}
                    className={`flex items-center gap-2 ${
                      ok ? "text-green-700" : "text-gray-600"
                    }`}
                  >
                    <span
                      aria-hidden="true"
                      className={`flex-shrink-0 w-4 h-4 rounded-full border flex items-center justify-center text-[10px] font-bold ${
                        ok
                          ? "border-green-600 bg-green-600 text-white"
                          : "border-gray-300 text-transparent"
                      }`}
                    >
                      ✓
                    </span>
                    <span className="sr-only">
                      {ok ? "Met: " : "Not met: "}
                    </span>
                    {rule.label}
                  </li>
                );
              })}
            </ul>
          </div>

          <Button type="submit" isLoading={loading} fullWidth>
            {loading ? "Creating account..." : "Create Account"}
          </Button>
        </form>

        <p className="text-center text-sm text-gray-500">
          Already have an account?{" "}
          <Link href="/login" className="text-blue-600 hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </main>
  );
}
