"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { AUTH_CONFIGURED } from "@/lib/supabase/config";

const LINKS = [
  { href: "/", label: "Live" },
  { href: "/history", label: "History" },
  { href: "/incidents", label: "Incidents" },
];

export default function Nav() {
  const pathname = usePathname();
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    if (!AUTH_CONFIGURED || pathname === "/login") return;
    createClient()
      .auth.getUser()
      .then(({ data }) => setEmail(data.user?.email ?? null));
  }, [pathname]);

  if (pathname === "/login") return null;

  async function signOut() {
    await createClient().auth.signOut();
    router.replace("/login");
    router.refresh();
  }

  return (
    <header className="border-b border-line bg-panel">
      <div className="max-w-7xl mx-auto px-4 h-14 flex items-center gap-6">
        <span className="font-semibold tracking-tight">Mill Signals</span>
        <nav className="flex gap-1 text-sm">
          {LINKS.map((l) => {
            const active = l.href === "/" ? pathname === "/" : pathname.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                className={`px-3 py-1.5 rounded-md ${active ? "bg-line text-foreground" : "text-muted hover:text-foreground"}`}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-3 text-sm">
          {AUTH_CONFIGURED ? (
            <>
              <span className="text-muted hidden sm:inline">{email}</span>
              <button onClick={signOut} className="px-3 py-1.5 rounded-md border border-line hover:bg-line">
                Sign out
              </button>
            </>
          ) : (
            <span className="text-amber-400 text-xs">auth off (local dev)</span>
          )}
        </div>
      </div>
    </header>
  );
}
