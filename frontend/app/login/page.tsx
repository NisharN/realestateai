"use client";

import { FormEvent, Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { createClient } from "@/lib/supabase/client";
import Link from "next/link";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const supabase = createClient();
      const { data, error: signInError } = await supabase.auth.signInWithPassword({
        email,
        password,
      });
      if (signInError || !data.user) throw signInError || new Error("Sign-in failed");

      const { data: memberships, error: membershipError } = await supabase
        .from("workspace_members")
        .select("workspace_id")
        .eq("user_id", data.user.id)
        .eq("status", "active")
        .limit(1);
      if (membershipError || !memberships?.[0]) {
        await supabase.auth.signOut();
        throw new Error("No active workspace membership");
      }
      localStorage.setItem("active_workspace_id", memberships[0].workspace_id);
      router.replace(searchParams.get("next") || "/dashboard");
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to sign in");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen bg-[#f4efe6] px-6 py-16 text-slate-950">
      <div className="mx-auto grid max-w-5xl overflow-hidden rounded-[2rem] bg-white shadow-2xl md:grid-cols-2">
        <section className="bg-slate-950 p-10 text-white md:p-14">
          <p className="text-sm font-semibold uppercase tracking-[0.24em] text-amber-300">Ali</p>
          <h1 className="mt-6 text-4xl font-semibold leading-tight">The private AI desk for Dubai property teams.</h1>
          <p className="mt-5 max-w-md text-slate-300">Invite-only access for brokers managing qualified leads, live inventory, and bilingual conversations.</p>
        </section>
        <section className="p-10 md:p-14">
          <h2 className="text-2xl font-semibold">Sign in to your workspace</h2>
          <p className="mt-2 text-sm text-slate-600">Use the account from your brokerage invitation.</p>
          <form className="mt-8 space-y-5" onSubmit={submit}>
            <label className="block text-sm font-medium">Email
              <input className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3 outline-none focus:border-slate-900" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
            </label>
            <label className="block text-sm font-medium">Password
              <input className="mt-2 w-full rounded-xl border border-slate-300 px-4 py-3 outline-none focus:border-slate-900" type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} />
            </label>
            {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
            <button className="w-full rounded-xl bg-slate-950 px-4 py-3 font-semibold text-white disabled:opacity-60" disabled={submitting} type="submit">
              {submitting ? "Signing in…" : "Sign in"}
            </button>
            <Link href="/forgot-password" className="block text-center text-sm text-slate-600 hover:text-slate-950">Forgot password?</Link>
          </form>
        </section>
      </div>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<main className="min-h-screen bg-[#f4efe6]" />}>
      <LoginForm />
    </Suspense>
  );
}
