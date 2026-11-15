import { Pool } from "pg";

declare global {
  var __pgPool: Pool | undefined;
}

export const pool = global.__pgPool ?? new Pool({
  host: process.env.POSTGRES_HOST ?? "localhost",
  port: Number(process.env.POSTGRES_PORT ?? 5432),
  database: process.env.POSTGRES_DB ?? "riverview_admissions",
  user: process.env.POSTGRES_USER ?? "postgres",
  password: process.env.POSTGRES_PASSWORD ?? "postgres",
  connectionTimeoutMillis: 5000,
  query_timeout: 10000,
});

if (process.env.NODE_ENV !== "production") global.__pgPool = pool;
