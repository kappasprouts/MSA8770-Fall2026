import { readFile } from "node:fs/promises";
import pg from "pg";
import { hashPassword } from "../src/lib/auth-crypto.mjs";

const client = new pg.Client({
  host: process.env.POSTGRES_HOST ?? "localhost", port: Number(process.env.POSTGRES_PORT ?? 5432),
  database: process.env.POSTGRES_DB ?? "riverview_admissions", user: process.env.POSTGRES_USER ?? "postgres",
  password: process.env.POSTGRES_PASSWORD ?? "postgres", connectionTimeoutMillis: 5000,
});

try {
  await client.connect();
  await client.query("BEGIN");
  await client.query(await readFile(new URL("../../storage/migrations/20261115_authentication.sql", import.meta.url), "utf8"));
  if (process.argv.includes("--seed-demo")) {
    // Existing accounts are preserved; this option creates missing synthetic demo accounts only.
    const demos = [
      ["USR001", "Lionel Haaland", "lionel.haaland@riverview.com", "ADMISSIONS_OFFICER", "OfficerDemo2026!"],
      ["USR002", "Caitlin Reese", "caitlin.reese@riverview.com", "DEAN", "DeanDemo2026!"],
      ["USR003", "Erling Mbappe", "erling.mbappe@riverview.com", "IT_SUPPORT", "ITDemo2026!"],
    ];
    for (const [id, name, email, role, password] of demos) {
      await client.query(`INSERT INTO system_users (user_id, full_name, email, role, password_hash)
        VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING`, [id, name, email, role, await hashPassword(password)]);
    }
  }
  const { rows } = await client.query("SELECT user_id, password FROM system_users WHERE password IS NOT NULL FOR UPDATE");
  for (const user of rows) {
    await client.query("UPDATE system_users SET password_hash = COALESCE(password_hash, $1), password = NULL WHERE user_id = $2", [await hashPassword(user.password), user.user_id]);
  }
  // Legacy passwords no longer authenticate; invalidate any sessions issued before migration.
  if (rows.length) await client.query("DELETE FROM auth_sessions");
  await client.query("COMMIT");
  console.log(`Authentication is ready. Converted ${rows.length} legacy password(s) to salted hashes.`);
} catch (error) {
  await client.query("ROLLBACK").catch(() => {});
  console.error("Authentication setup failed:", error.code ?? error.message);
  process.exitCode = 1;
} finally { await client.end(); }
