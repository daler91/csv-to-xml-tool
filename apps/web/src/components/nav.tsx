"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession, signOut } from "next-auth/react";
import { useEffect, useState } from "react";

export function Nav() {
  const { data: session } = useSession();
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  // Close the mobile menu on route change.
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  if (!session) return null;

  const links = [
    { href: "/dashboard", label: "Dashboard" },
    { href: "/convert", label: "Convert" },
    { href: "/audit", label: "Audit Trail" },
    { href: "/help", label: "Help" },
  ];

  const isActive = (href: string) =>
    pathname === href || pathname.startsWith(href + "/");

  return (
    <nav className="border-b bg-white">
      <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
        {/* Desktop layout */}
        <div className="hidden md:flex items-center gap-6">
          <Link href="/dashboard" className="font-semibold text-lg">
            CSV to XML Converter
          </Link>
          {links.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className={`text-sm ${
                isActive(href)
                  ? "text-blue-600 font-medium"
                  : "text-gray-600 hover:text-gray-900"
              }`}
            >
              {label}
            </Link>
          ))}
        </div>
        <div className="hidden md:flex items-center gap-4">
          <span className="text-sm text-gray-600 truncate max-w-48">
            {session.user.email}
          </span>
          <button
            onClick={() => signOut({ callbackUrl: "/" })}
            className="text-sm text-gray-600 hover:text-gray-900"
          >
            Sign Out
          </button>
        </div>

        {/* Mobile layout */}
        <Link
          href="/dashboard"
          className="md:hidden font-semibold text-lg"
        >
          CSV to XML Converter
        </Link>
        <button
          type="button"
          aria-label={mobileOpen ? "Close menu" : "Open menu"}
          aria-expanded={mobileOpen}
          aria-controls="mobile-nav"
          onClick={() => setMobileOpen((v) => !v)}
          className="md:hidden p-2 -mr-2 text-gray-600 hover:text-gray-900"
        >
          {mobileOpen ? (
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          ) : (
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          )}
        </button>
      </div>

      {/* Mobile dropdown sheet */}
      {mobileOpen && (
        <div
          id="mobile-nav"
          className="md:hidden border-t bg-white"
        >
          <ul className="flex flex-col px-4 py-2 divide-y divide-gray-100">
            {links.map(({ href, label }) => (
              <li key={href}>
                <Link
                  href={href}
                  className={`block py-3 text-sm ${
                    isActive(href)
                      ? "text-blue-600 font-medium"
                      : "text-gray-700 hover:text-gray-900"
                  }`}
                >
                  {label}
                </Link>
              </li>
            ))}
            <li>
              <div className="py-3 text-xs text-gray-500 truncate">
                Signed in as {session.user.email}
              </div>
            </li>
            <li>
              <button
                type="button"
                onClick={() => signOut({ callbackUrl: "/" })}
                className="block w-full text-left py-3 text-sm text-gray-700 hover:text-gray-900"
              >
                Sign Out
              </button>
            </li>
          </ul>
        </div>
      )}
    </nav>
  );
}
