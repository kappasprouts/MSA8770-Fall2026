import { NextResponse } from "next/server";
import { buildDossierContext, buildSystemPrompt, loadDossier } from "@/lib/dossier";
import { isAdvisoryReply, parseChatInput } from "@/lib/chat-guards";

export const dynamic = "force-dynamic";

const OLLAMA_CHAT_URL = process.env.OLLAMA_CHAT_URL ?? "http://localhost:11434/api/chat";
const OLLAMA_MODEL = process.env.OLLAMA_MODEL ?? "qwen3-vl:8b-instruct";

export async function POST(request: Request) {
  let body: unknown;

  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid request body." }, { status: 400 });
  }

  const input = parseChatInput(body);
  if (!input) {
    return NextResponse.json(
      { error: "Provide an applicant ID and a bounded conversation using user/assistant text messages, ending in a user question." },
      { status: 400 }
    );
  }

  const { appId, messages } = input;
  let dossierData;
  try {
    dossierData = await loadDossier(appId);
  } catch {
    return NextResponse.json({ error: "The dossier service is unavailable." }, { status: 503 });
  }

  if (!dossierData) {
    return NextResponse.json(
      { error: `No dossier found for applicant "${appId}".` },
      { status: 404 }
    );
  }

  const systemPrompt = buildSystemPrompt(buildDossierContext(dossierData));

  const payload = {
    model: OLLAMA_MODEL,
    stream: false,
    options: {
      num_ctx: 8192,
      num_predict: 2048,
    },
    messages: [{ role: "system", content: systemPrompt }, ...messages],
  };

  try {
    const response = await fetch(OLLAMA_CHAT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(60000),
    });
    if (!response.ok) {
      return NextResponse.json({ error: "The model service could not complete the request." }, { status: 502 });
    }
    const data = await response.json();
    const reply = data?.message?.content;
    if (data?.done !== true || data?.done_reason === "length" || typeof reply !== "string" || !isAdvisoryReply(reply)) {
      return NextResponse.json({ error: "The assistant did not return a complete advisory response. Review the dossier or try again." }, { status: 502 });
    }
    return NextResponse.json({ reply });
  } catch (error) {
    const timedOut = error instanceof Error && ["AbortError", "TimeoutError"].includes(error.name);
    return NextResponse.json(
      { error: timedOut ? "The assistant timed out. Review the dossier or try again." : "The model service is unavailable or returned an invalid response." },
      { status: timedOut ? 504 : 502 }
    );
  }
}
