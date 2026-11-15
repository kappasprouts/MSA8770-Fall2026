"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { requestJson } from "@/lib/http";
import styles from "@/app/login/login.module.css";

export default function LoginForm({ returnTo }: { returnTo: string }) {
  const router = useRouter();
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    setBusy(true); setError("");
    try {
      const result = await requestJson<{ redirectTo: string }>("/api/auth/login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ userId: fields.get("userId"), password: fields.get("password"), returnTo }),
      });
      router.replace(result.redirectTo);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in. Please try again.");
      const input = form.elements.namedItem("password") as HTMLInputElement;
      input.value = ""; input.focus(); setBusy(false);
    }
  }
  return <form onSubmit={signIn} className={styles.form} aria-busy={busy}>
    {error && <div className={styles.error} role="alert">{error}</div>}
    <label htmlFor="userId">User ID</label>
    <input id="userId" name="userId" autoComplete="username" placeholder="User ID" required maxLength={20} disabled={busy} />
    <label htmlFor="password">Password</label>
    <div className={styles.password}>
      <input id="password" name="password" type={visible ? "text" : "password"} autoComplete="current-password" placeholder="Password" required maxLength={1024} disabled={busy} />
      <button type="button" onClick={() => setVisible(!visible)} aria-label={visible ? "Hide password" : "Show password"} aria-pressed={visible}>{visible ? "Hide" : "Show"}</button>
    </div>
    <button className={styles.submit} type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign In"}</button>
  </form>;
}
