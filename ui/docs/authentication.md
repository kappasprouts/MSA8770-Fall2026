# Sign-in and role-based access

Home (`/`) is public. Selecting a protected workspace opens `/login` and preserves the selected page and query parameters. After the User ID and password are verified against `system_users`, the server checks the stored role and routes the user to that page or `/access-denied`. Signed-in navigation shows only permitted workspaces. Sign Out revokes the browser's session and returns to Home.

| Workspace | Admissions Officer | Dean | IT Support |
| --- | --- | --- | --- |
| Home | Public | Public | Public |
| Processing Dashboard | Allowed | Denied | Denied |
| Applicant Review, source PDFs, Q&A, recommendations | Allowed | Allowed | Denied |
| Final Decisions | Denied | Allowed | Denied |
| Summary Statistics | Allowed | Allowed | Denied |
| IT Error Queue and incident details | Denied | Denied | Allowed |

The database role `ADMISSIONS_OFFICER` corresponds to Officer in the diagrams. The other roles are `DEAN` and `IT_SUPPORT`. Users cannot choose or submit their own role at login. Both pages and data APIs enforce this matrix, including direct URLs and API requests. Recommendation and final-decision audit events store the authenticated `user_id` and role.

## Local setup

Start PostgreSQL and configure `ui/.env.local` with the existing `POSTGRES_*` settings. From `ui`, run:

```bash
npm run auth:setup -- --seed-demo
npm run dev
```

The setup command applies `storage/migrations/20261115_authentication.sql`. It creates missing authentication tables, adds `password_hash` to existing accounts, converts any legacy plaintext `password` values to salted scrypt hashes, clears the plaintext column, and revokes sessions for a legacy-password migration. It can be rerun. The optional `--seed-demo` flag creates missing demo accounts without replacing existing accounts or their passwords; omit it when migrating your own users. Existing accounts without a password hash or legacy password cannot sign in.

Open <http://localhost:3000> or the port shown by the development server. These synthetic demo credentials are for local testing:

| User ID | Password | Role |
| --- | --- | --- |
| `USR001` | `OfficerDemo2026!` | Admissions Officer |
| `USR002` | `DeanDemo2026!` | Dean |
| `USR003` | `ITDemo2026!` | IT Support |

If the database predates recommendations, also apply the existing `20261102_reviewer_recommendation.sql` migration as described in the root setup guide.

## Session and API behavior

- Sessions last eight hours. The browser holds a random opaque token in an HttpOnly, SameSite=Lax cookie; PostgreSQL holds only its SHA-256 hash. Cookies are Secure in production and over HTTPS. Production hosting requires HTTPS.
- Each protected request checks session expiry and the account's current role and `is_active` value. Disabling an account or changing its role takes effect on subsequent requests. Logout deletes the session, and successful login rotates the browser's previous token.
- Passwords are verified on the server with salted scrypt hashes. Unknown, inactive, and incorrect-password logins return the same error. Ten attempts per User ID are allowed within a 15-minute window before throttling; the counter persists in PostgreSQL.
- Mutating requests require an Origin header matching the portal origin. A separate API client must send that origin and the session cookie. Session tokens are not placed in local storage or URLs. Original PDF responses use `private, no-store`.
- Protected APIs return `401` when sign-in is required, `403` for a role or origin mismatch, and `503` when the authentication database is unavailable. Login returns `429` with `Retry-After` when throttled. Database failure never grants access.

The implementation supplies local account authentication. Account provisioning, password recovery, university SSO and MFA are outside this feature. Use managed university accounts and HTTPS before using real admissions data.

## Verification

```bash
npm test
npm run lint
npm run build
```

To include the database-backed SQL tests, run `node --env-file=.env.local --test tests/*.test.mjs`. With a local UI running on port 3001, run:

```bash
node --env-file=.env.local tests/auth-integration.mjs
```

Set `AUTH_TEST_BASE_URL` for another local port. The integration script creates unique test users and one synthetic applicant, exercises permissions and review audit writes, then removes its test rows. It does not change existing applicants or account passwords. It covers login routing, all three roles, invalid and inactive accounts, forged cookies, expired sessions, logout, cross-origin login, and throttling.
