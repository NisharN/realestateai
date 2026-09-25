"use client";

import { FormEvent, useEffect, useState } from "react";
import { membersApi, type WorkspaceMember } from "@/lib/api";

export default function MembersPage() {
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<WorkspaceMember["role"]>("agent");
  const [message, setMessage] = useState<string | null>(null);

  async function load() {
    const result = await membersApi.list();
    if (result.data) setMembers(result.data);
    else setMessage(result.error ?? "Unable to load members");
  }

  useEffect(() => { void load(); }, []);

  async function invite(event: FormEvent) {
    event.preventDefault();
    const result = await membersApi.invite({ email, role });
    if (result.error) return setMessage(result.error);
    setEmail("");
    setMessage("Invitation sent.");
    await load();
  }

  return <main className="min-h-full px-5 py-10"><div className="mx-auto max-w-5xl"><h1 className="text-3xl font-semibold">Workspace members</h1><p className="mt-2 text-muted-foreground">Invite agents and control access for this brokerage.</p><form onSubmit={invite} className="mt-8 grid gap-3 rounded-2xl bg-card p-5 shadow-card md:grid-cols-[1fr_180px_auto]"><input aria-label="Email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="agent@brokerage.ae" className="rounded-xl border px-4 py-3"/><select aria-label="Role" value={role} onChange={(e) => setRole(e.target.value as WorkspaceMember["role"])} className="rounded-xl border px-4 py-3"><option value="agent">Agent</option><option value="admin">Admin</option><option value="owner">Owner</option></select><button className="rounded-xl bg-brand px-5 py-3 font-semibold text-white">Send invitation</button></form>{message && <p role="status" className="mt-4 text-sm text-foreground/80">{message}</p>}<div className="mt-8 overflow-hidden rounded-2xl border border-border bg-card"><table className="w-full text-left text-sm"><thead className="bg-muted"><tr><th className="p-4">User</th><th className="p-4">Role</th><th className="p-4">Status</th></tr></thead><tbody>{members.map((member) => <tr key={member.user_id} className="border-t"><td className="p-4 font-mono text-xs">{member.user_id}</td><td className="p-4 capitalize">{member.role}</td><td className="p-4 capitalize">{member.status}</td></tr>)}</tbody></table></div></div></main>;
}
