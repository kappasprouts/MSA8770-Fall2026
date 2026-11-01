export interface ChatMessage { role: "user" | "assistant"; content: string }
export interface ChatInput { appId: string; messages: ChatMessage[] }

export function parseChatInput(value: unknown): ChatInput | null {
  if (!value || typeof value !== "object" || !("appId" in value) || !("messages" in value)) return null;
  if (typeof value.appId !== "string" || !value.appId.trim() || value.appId.length > 64 ||
      !Array.isArray(value.messages) || !value.messages.length || value.messages.length > 40) return null;
  const messages: ChatMessage[] = [];
  let total = 0;
  for (const message of value.messages) {
    if (!message || typeof message !== "object" ||
        (message.role !== "user" && message.role !== "assistant") ||
        typeof message.content !== "string" || !message.content.trim() || message.content.length > 12000) return null;
    total += message.content.length;
    if (total > 48000) return null;
    // Reconstruct the wire messages rather than forwarding client objects.
    messages.push({ role: message.role, content: message.content });
  }
  if (messages[0].role !== "user" || messages[messages.length - 1].role !== "user") return null;
  return { appId: value.appId.trim(), messages };
}

const decisionPatterns = [
  /^\s*(?:accept|admit|reject|deny|decline|waitlist)(?:ed)?[.!]?\s*$/i,
  /\b(?:final\s+)?(?:decision|recommendation)\s*(?:is\s*|:|=)\s*(?:accept|admit|reject|deny|decline|waitlist)\b/i,
  /\b(?:admit|accept|reject|deny|waitlist)\s+(?:this|the)\s+(?:applicant|candidate|student)\b/i,
  /\brecommend(?:ed)?\s+(?:admitting|accepting|rejecting|denying|waitlisting)\b/i,
  /\b(?:applicant|candidate|student|they|he|she)\s+(?:should|must|will|would)\s+be\s+(?:admitted|accepted|rejected|denied|waitlisted)\b/i,
  /\brecommend(?:ed)?\s+(?:the\s+)?(?:applicant|candidate|student)\s+for\s+admission\b/i,
];

export function isAdvisoryReply(reply: string): boolean {
  return Boolean(reply.trim()) && !decisionPatterns.some(pattern => pattern.test(reply));
}
