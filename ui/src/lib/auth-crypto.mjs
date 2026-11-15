import { randomBytes, scrypt, timingSafeEqual, createHash } from "node:crypto";
import { promisify } from "node:util";

const derive = promisify(scrypt);
const options = { N: 16384, r: 8, p: 1 };

export async function hashPassword(password) {
  const salt = randomBytes(16).toString("hex");
  const key = await derive(password, salt, 64, options);
  return `scrypt$${salt}$${key.toString("hex")}`;
}

export async function verifyPassword(password, hash) {
  if (typeof password !== "string" || password.length > 1024 || typeof hash !== "string") return false;
  const parts = hash.split("$");
  if (parts.length !== 3 || parts[0] !== "scrypt" || !/^[a-f0-9]{32}$/.test(parts[1]) || !/^[a-f0-9]{128}$/.test(parts[2])) return false;
  const key = await derive(password, parts[1], 64, options);
  return timingSafeEqual(key, Buffer.from(parts[2], "hex"));
}

export const newSessionToken = () => randomBytes(32).toString("hex");
export const tokenHash = token => createHash("sha256").update(token).digest("hex");

// An unknown account still incurs a password derivation to reduce account enumeration.
export const DUMMY_PASSWORD_HASH = `scrypt$${"0".repeat(32)}$${"0".repeat(128)}`;
