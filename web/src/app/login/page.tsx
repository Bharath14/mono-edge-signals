"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { createClient } from "@/lib/supabase/client";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    const auth = createClient().auth;
    const { data, error } =
      mode === "signin"
        ? await auth.signInWithPassword({ email, password })
        : await auth.signUp({ email, password });
    setBusy(false);
    if (error) return setError(error.message);
    if (!data.session) {
      // Sign-up with email confirmation turned on: no session until confirmed.
      return setNotice("Check your email to confirm the account, then sign in.");
    }
    router.replace("/");
    router.refresh();
  }

  return (
    <div className="min-h-[80vh] flex items-center justify-center">
      <form onSubmit={submit} className="w-full max-w-sm bg-panel border border-line rounded-xl p-6 space-y-4">
        <div>
          <h1 className="text-xl font-semibold">Mill Signals</h1>
          <p className="text-sm text-muted">
            {mode === "signin" ? "Sign in to monitor the mill." : "Create an operator account."}
          </p>
        </div>
        <label className="block text-sm">
          <span className="text-muted">Email</span>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded-md bg-background border border-line px-3 py-2"
          />
        </label>
        <label className="block text-sm">
          <span className="text-muted">Password</span>
          <input
            type="password"
            required
            minLength={6}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded-md bg-background border border-line px-3 py-2"
          />
        </label>
        {error && <p className="text-sm text-red-400">{error}</p>}
        {notice && <p className="text-sm text-emerald-400">{notice}</p>}
        <button
          disabled={busy}
          className="w-full rounded-md bg-sky-600 hover:bg-sky-500 disabled:opacity-50 py-2 font-medium"
        >
          {busy ? "Please wait…" : mode === "signin" ? "Sign in" : "Sign up"}
        </button>
        <button
          type="button"
          onClick={() => setMode(mode === "signin" ? "signup" : "signin")}
          className="w-full text-sm text-muted hover:text-foreground"
        >
          {mode === "signin" ? "No account? Sign up" : "Have an account? Sign in"}
        </button>
      </form>
    </div>
  );
}
