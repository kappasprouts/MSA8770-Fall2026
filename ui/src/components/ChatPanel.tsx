"use client";

import { KeyboardEvent, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  isError?: boolean;
  time: string;
}

function createId() {
  return Math.random().toString(36).slice(2);
}

function nowLabel() {
  return new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export default function ChatPanel({ appId }: { appId: string }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function sendMessage() {
    const trimmed = input.trim();

    if (!trimmed || !appId || loading) {
      return;
    }

    const userMessage: ChatMessage = {
      id: createId(),
      role: "user",
      content: trimmed,
      time: nowLabel(),
    };
    const nextMessages = [...messages, userMessage];

    setMessages(nextMessages);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          appId,
          messages: nextMessages.map(({ role, content }) => ({ role, content })),
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        setMessages((prev) => [
          ...prev,
          {
            id: createId(),
            role: "assistant",
            content: data.error ?? "Something went wrong.",
            isError: true,
            time: nowLabel(),
          },
        ]);
      } else {
        setMessages((prev) => [
          ...prev,
          {
            id: createId(),
            role: "assistant",
            content: data.reply || "(no response)",
            time: nowLabel(),
          },
        ]);
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: createId(),
          role: "assistant",
          content: "Network error reaching the chat API.",
          isError: true,
          time: nowLabel(),
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col rounded-xl border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border bg-panel-header px-4 py-3">
        <h2 className="text-sm font-semibold text-ink">Q&amp;A Assistant</h2>
        <span className="text-xs text-ink-muted">↕ Scroll</span>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        {messages.length === 0 && (
          <p className="text-sm text-ink-muted">
            Ask about this applicant&apos;s academics, activities, recommendations, essay, or
            policy alignment. Answers are grounded in the validated dossier only.
          </p>
        )}

        {messages.map((message) => (
          <div key={message.id} className="flex items-start gap-3">
            <span
              className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                message.role === "user"
                  ? "bg-accent/20 text-accent"
                  : "bg-card-green-border/40 text-card-green-text"
              }`}
            >
              {message.role === "user" ? "Q" : "A"}
            </span>

            <div className="min-w-0 flex-1">
              <div
                className={`inline-block max-w-full rounded-xl px-3 py-2 text-sm leading-relaxed ${
                  message.isError
                    ? "border border-red-200 bg-red-50 text-red-700"
                    : "bg-surface-alt text-ink [&_p]:my-1 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0 [&_strong]:font-semibold [&_ul]:list-disc [&_ul]:pl-4"
                }`}
              >
                {message.role === "assistant" && !message.isError ? (
                  <ReactMarkdown>{message.content}</ReactMarkdown>
                ) : (
                  <span className="whitespace-pre-wrap">{message.content}</span>
                )}
              </div>
              <p className="mt-1 text-[11px] text-ink-muted">{message.time}</p>
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex items-start gap-3">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-card-green-border/40 text-xs font-bold text-card-green-text">
              A
            </span>
            <div className="rounded-xl bg-surface-alt px-3 py-2 text-sm text-ink-muted">Thinking…</div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      <div className="border-t border-border p-3">
        <div className="flex items-end gap-2">
          <textarea
            className="h-20 flex-1 resize-none rounded-lg border border-border bg-surface-alt px-3 py-2 text-sm text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none"
            placeholder='Ask about this applicant (e.g., "What do the recommendation letters say?")'
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleKeyDown}
            disabled={!appId}
          />
          <button
            type="button"
            onClick={sendMessage}
            disabled={!appId || !input.trim() || loading}
            className="flex h-20 items-center gap-1.5 rounded-lg bg-accent-strong px-4 text-sm font-semibold text-white transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            Send ➤
          </button>
        </div>
      </div>
    </div>
  );
}
