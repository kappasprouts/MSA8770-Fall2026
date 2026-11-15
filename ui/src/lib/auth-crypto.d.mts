export function hashPassword(password: string): Promise<string>;
export function verifyPassword(password: string, hash: string | null): Promise<boolean>;
export function newSessionToken(): string;
export function tokenHash(token: string): string;
export const DUMMY_PASSWORD_HASH: string;
