"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

export default function ResetPasswordPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (password.length < 12) return setError("Use at least 12 characters.");
    const { error: updateError } = await createClient().auth.updateUser({ password });
    if (updateError) return setError(updateError.message);
    router.replace("/dashboard");
  }

  return <main className="min-h-screen bg-[#f4efe6] px-6 py-20"><form onSubmit={submit} className="mx-auto max-w-md rounded-3xl bg-white p-10 shadow-xl"><h1 className="text-2xl font-semibold">Set a new password</h1><label className="mt-8 block text-sm font-medium">New password<input type="password" minLength={12} required value={password} onChange={(e) => setPassword(e.target.value)} className="mt-2 w-full rounded-xl border px-4 py-3" /></label>{error && <p role="alert" className="mt-4 text-sm text-red-700">{error}</p>}<button className="mt-6 w-full rounded-xl bg-slate-950 py-3 font-semibold text-white">Update password</button></form></main>;
}
