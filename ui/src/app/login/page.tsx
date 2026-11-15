import Link from "next/link";
import { redirect } from "next/navigation";
import Logo from "@/components/Logo";
import LoginForm from "@/components/LoginForm";
import { currentUser } from "@/lib/auth";
import { canAccess, pagePermission, safeReturnTo } from "@/lib/auth-policy";
import styles from "./login.module.css";

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const params = await searchParams;
  const returnTo = safeReturnTo(params.returnTo);
  const user = await currentUser().catch(() => null);
  if (user) {
    const permission = pagePermission(new URL(returnTo, "https://portal.invalid").pathname);
    redirect(permission && !canAccess(user.role, permission) ? "/access-denied" : returnTo);
  }
  return <main className={styles.page}>
    <section className={styles.card} aria-labelledby="login-title">
      <Link href="/" className={styles.brand} aria-label="Riverview State University home"><Logo className="h-14 w-14" /><span>Riverview State University</span></Link>
      <p className={styles.portal}>Admissions Portal</p>
      <h1 id="login-title">Sign In</h1>
      <p className={styles.description}>Use your university account to access your workspace.</p>
      <LoginForm returnTo={returnTo} />
      <Link href="/" className={styles.home}>← Return to Home</Link>
    </section>
  </main>;
}
