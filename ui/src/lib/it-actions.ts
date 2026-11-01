export const IT_ACTIONS = ["CLAIM", "NOTE", "HANDOFF", "REQUEST_RETRY", "VERIFY_RESOLVED"] as const;
export type ItAction = typeof IT_ACTIONS[number];
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
export function parseItAction(value: unknown) {
  if (!value || typeof value !== "object") return null;
  const v = value as Record<string, unknown>;
  if (!IT_ACTIONS.includes(v.action as ItAction) || typeof v.commandId !== "string" || !uuid.test(v.commandId) ||
    typeof v.fingerprint !== "string" || !/^[a-f0-9]{64}$/.test(v.fingerprint) ||
    !Number.isSafeInteger(v.revision) || Number(v.revision) < 0 ||
    typeof v.actor !== "string" || !v.actor.trim() || v.actor.length > 200 ||
    typeof v.note !== "string" || !v.note.trim() || v.note.length > 10000 ||
    typeof v.confirmed !== "boolean" ||
    (["REQUEST_RETRY", "VERIFY_RESOLVED"].includes(String(v.action)) && v.confirmed !== true) ||
    (v.action === "HANDOFF" && (typeof v.owner !== "string" || !v.owner.trim() || v.owner.length > 200))) return null;
  return { action: v.action as ItAction, commandId: v.commandId, fingerprint: v.fingerprint,
    revision: Number(v.revision), actor: v.actor.trim(), note: v.note.trim(),
    confirmed: v.confirmed, owner: typeof v.owner === "string" ? v.owner.trim() : "" };
}
export type ItCommand = NonNullable<ReturnType<typeof parseItAction>>;
