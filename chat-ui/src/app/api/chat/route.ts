import { NextResponse } from "next/server";
import { buildDossierContext, buildSystemPrompt, loadDossier } from "@/lib/dossier";

export const dynamic = "force-dynamic";

const OLLAMA_CHAT_URL = process.env.OLLAMA_CHAT_URL ?? "http://localhost:11434/api/chat";
const OLLAMA_MODEL = process.env.OLLAMA_MODEL ?? "qwen3-vl:8b-instruct";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface ChatRequestBody {
  appId?: string;
  messages?: ChatMessage[];
}

export async function POST(request: Request) {
  let body: ChatRequestBody;

  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid request body." }, { status: 400 });
  }

  const { appId, messages } = body;

  if (!appId || !Array.isArray(messages) || messages.length === 0) {
    return NextResponse.json(
      { error: "appId and a non-empty messages array are required." },
      { status: 400 }
    );
  }

  const dossierData = await loadDossier(appId);

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

  let response: Response;

  try {
    response = await fetch(OLLAMA_CHAT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    return NextResponse.json(
      {
        error:
          `Could not reach Ollama at ${OLLAMA_CHAT_URL}. ` +
          "Make sure `ollama serve` is running and the model is pulled " +
          `(\`ollama pull ${OLLAMA_MODEL}\`).`,
      },
      { status: 502 }
    );
  }

  if (!response.ok) {
    const text = await response.text();
    return NextResponse.json({ error: `Ollama returned an error: ${text}` }, { status: 502 });
  }
  
  const data = await response.json();
  const reply: string = data?.message?.content ?? "";

  console.log("Ollama chat result:", {
    done_reason: data?.done_reason,
    eval_count: data?.eval_count,
    reply_length: reply.length,
  });

  return NextResponse.json({ reply });

}
