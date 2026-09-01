"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { createClient } from "@/lib/supabase/client";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const redirectTo = `${window.location.origin}/reset-password`;
    const { error } = await createClient().auth.resetPasswordForEmail(email, { redirectTo });
    setMessage(error ? error.message : "If that account exists, a recovery link has been sent.");
  }

  return <main className="min-h-screen bg-[#f4efe6] px-6 py-20"><form onSubmit={submit} className="mx-auto max-w-md rounded-3xl bg-white p-10 shadow-xl"><h1 className="text-2xl font-semibold">Recover your account</h1><p className="mt-2 text-sm text-slate-600">We will email a secure password-reset link.</p><label className="mt-8 block text-sm font-medium">Email<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className="mt-2 w-full rounded-xl border px-4 py-3" /></label>{message && <p role="status" className="mt-4 text-sm">{message}</p>}<button className="mt-6 w-full rounded-xl bg-slate-950 py-3 font-semibold text-white">Send recovery link</button><Link href="/login" className="mt-5 block text-center text-sm text-slate-600">Back to sign in</Link></form></main>;
}
