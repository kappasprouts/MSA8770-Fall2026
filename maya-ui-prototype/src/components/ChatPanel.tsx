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

const SUGGESTIONS = [
  "Summarize the applicant's academic record.",
  "What do the recommendation letters emphasize?",
  "Which policies were applied to this dossier?",
];

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
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-border bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-surface-alt px-5 py-4">
        <div>
          <h2 className="font-semibold text-ink">Grounded officer Q&amp;A</h2>
          <p className="mt-0.5 text-xs text-ink-muted">Answers use only the validated applicant dossier.</p>
        </div>
        <span className="rounded-full border border-violet-200 bg-violet-50 px-2.5 py-1 text-[11px] font-semibold text-violet-700">
          Applicant {appId}
        </span>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        {messages.length === 0 && (
          <div className="rounded-xl border border-dashed border-border bg-surface-alt p-5">
            <p className="text-sm text-ink-muted">
              Ask about this applicant&apos;s academics, activities, recommendations, supplement, or policy alignment.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => setInput(suggestion)}
                  className="rounded-full border border-border bg-white px-3 py-2 text-xs font-medium text-ink-muted transition hover:border-accent hover:text-accent"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
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

      <div className="border-t border-border bg-surface-alt p-3">
        <div className="flex items-end gap-2">
          <textarea
            className="h-20 flex-1 resize-none rounded-xl border border-border bg-white px-3 py-2 text-sm text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none"
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
            className="flex h-20 items-center gap-1.5 rounded-xl bg-accent-strong px-5 text-sm font-semibold text-white transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            Send ➤
          </button>
        </div>
      </div>
    </div>
  );
}
