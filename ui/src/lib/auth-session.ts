import { pool } from "./db";
import { isRole, type SessionUser } from "./auth-policy";
import { tokenHash } from "./auth-crypto.mjs";

export const SESSION_COOKIE = "rsu_session";
export const SESSION_SECONDS = 8 * 60 * 60;

export async function sessionUser(token?: string): Promise<SessionUser | null> {
  if (!token || !/^[a-f0-9]{64}$/.test(token)) return null;
  const { rows } = await pool.query(
    `SELECT u.user_id, u.full_name, u.role FROM auth_sessions s
     JOIN system_users u ON u.user_id = s.user_id
     WHERE s.token_hash = $1 AND s.expires_at > NOW() AND u.is_active = TRUE`,
    [tokenHash(token)],
  );
  const user = rows[0];
  return user && isRole(user.role) ? { userId: user.user_id, fullName: user.full_name, role: user.role } : null;
}
