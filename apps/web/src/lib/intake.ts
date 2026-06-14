// Chat intake brain — an OpenAI assistant that turns a free-text purchase
// request into a structured Order. It asks 1–2 clarifying questions, then
// extracts { title, category?, brand?, maxBudgetCents } and signals `ready`.
//
// Robustness is a hard requirement: if OpenAI errors or no key is set, we fall
// back to a deterministic extraction from the raw text so an Order can always be
// created. Money is integer cents.

import OpenAI from "openai";

export interface Extracted {
  title: string | null;
  category: string | null;
  brand: string | null;
  maxBudgetCents: number | null;
}

export interface IntakeTurn {
  reply: string;
  extracted: Extracted;
  ready: boolean;
}

export interface IntakeMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

const MODEL = process.env.OPENAI_INTAKE_MODEL || "gpt-4o-mini";

const SYSTEM_PROMPT = `You are sivra's purchase-intake assistant. An employee describes something they want to buy. Your job:
1. Understand WHAT they want to buy.
2. Ask at most 1–2 short clarifying questions ONLY if you're missing the essentials (what the item is, and a budget). Keep questions friendly and brief.
3. Once you have enough to start a search, set ready=true and stop asking.

Always return a concise, warm assistant reply (1–3 sentences). Never invent a brand or budget the user didn't imply.

Extract these fields when present:
- title: a short noun phrase describing the item (e.g. "ergonomic office chair", "MacBook Pro 14\\"").
- category: a coarse category if obvious (e.g. "furniture", "electronics", "office supplies"), else null.
- brand: a specific brand if the user named one, else null.
- maxBudgetCents: the user's maximum budget in integer cents (EUR). Parse phrases like "under 500", "€1,200", "about 80 euros". null if not stated.

Set ready=true when you have at least a usable title AND either a budget or the user has confirmed they want to proceed. Otherwise ready=false and your reply should contain your clarifying question.`;

interface ToolArgs {
  reply: string;
  ready: boolean;
  title?: string | null;
  category?: string | null;
  brand?: string | null;
  maxBudgetCents?: number | null;
}

const EXTRACT_TOOL = {
  type: "function" as const,
  function: {
    name: "intake_result",
    description:
      "Return the assistant reply plus the structured fields extracted so far.",
    parameters: {
      type: "object",
      properties: {
        reply: {
          type: "string",
          description: "The assistant's natural-language reply to show the user.",
        },
        ready: {
          type: "boolean",
          description:
            "True if there's enough to create + launch the order now.",
        },
        title: { type: ["string", "null"], description: "Short item title." },
        category: { type: ["string", "null"] },
        brand: { type: ["string", "null"] },
        maxBudgetCents: {
          type: ["integer", "null"],
          description: "Max budget in integer cents (EUR).",
        },
      },
      required: ["reply", "ready"],
      additionalProperties: false,
    },
  },
};

/**
 * Run one intake turn over the conversation so far. Returns the assistant reply,
 * the cumulative extraction, and whether we're ready to create+launch. Never
 * throws — falls back to a deterministic extraction on any OpenAI error.
 */
export async function runIntakeTurn(
  history: IntakeMessage[],
  latestUserMessage: string,
  priorExtracted?: Partial<Extracted>,
): Promise<IntakeTurn> {
  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) {
    return fallbackTurn(latestUserMessage, priorExtracted);
  }

  try {
    const client = new OpenAI({ apiKey });
    const messages: OpenAI.Chat.ChatCompletionMessageParam[] = [
      { role: "system", content: SYSTEM_PROMPT },
    ];
    if (priorExtracted && hasAnyField(priorExtracted)) {
      messages.push({
        role: "system",
        content: `Fields extracted so far: ${JSON.stringify(priorExtracted)}. Merge new info; don't drop known fields.`,
      });
    }
    for (const m of history) {
      if (m.role === "system") continue;
      messages.push({ role: m.role, content: m.content });
    }
    messages.push({ role: "user", content: latestUserMessage });

    const completion = await client.chat.completions.create({
      model: MODEL,
      messages,
      tools: [EXTRACT_TOOL],
      tool_choice: { type: "function", function: { name: "intake_result" } },
      temperature: 0.3,
    });

    const call = completion.choices[0]?.message?.tool_calls?.[0];
    if (!call || call.function.name !== "intake_result") {
      return fallbackTurn(latestUserMessage, priorExtracted);
    }
    const args = JSON.parse(call.function.arguments) as ToolArgs;

    const extracted = mergeExtracted(priorExtracted, {
      title: nullableStr(args.title),
      category: nullableStr(args.category),
      brand: nullableStr(args.brand),
      maxBudgetCents: nullableInt(args.maxBudgetCents),
    });

    // Don't claim ready without at least a title.
    const ready = Boolean(args.ready) && Boolean(extracted.title);

    return {
      reply:
        nullableStr(args.reply) ??
        "Got it — let me start the search for you.",
      extracted,
      ready,
    };
  } catch (err) {
    console.warn("[intake] OpenAI turn failed, using fallback:", err);
    return fallbackTurn(latestUserMessage, priorExtracted);
  }
}

// ── Deterministic fallback (no OpenAI / on error) ──────────────────────────────
function fallbackTurn(
  userMessage: string,
  prior?: Partial<Extracted>,
): IntakeTurn {
  const text = userMessage.trim();
  const budget = parseBudgetCents(text);
  const title =
    prior?.title ?? (text ? truncateTitle(text) : null);
  const extracted = mergeExtracted(prior, {
    title,
    category: prior?.category ?? null,
    brand: prior?.brand ?? null,
    maxBudgetCents: prior?.maxBudgetCents ?? budget,
  });

  // First turn with no budget → ask once; otherwise proceed.
  const haveBudget = extracted.maxBudgetCents != null;
  const ready = Boolean(extracted.title);
  const reply = haveBudget
    ? "Got it — I'll start the search for you now."
    : "Got it. Do you have a maximum budget in mind? I can also just start searching.";

  return { reply, extracted, ready };
}

// ── helpers ────────────────────────────────────────────────────────────────────
function hasAnyField(e: Partial<Extracted>): boolean {
  return Boolean(e.title || e.category || e.brand || e.maxBudgetCents != null);
}

function mergeExtracted(
  prior: Partial<Extracted> | undefined,
  next: Extracted,
): Extracted {
  return {
    title: next.title ?? prior?.title ?? null,
    category: next.category ?? prior?.category ?? null,
    brand: next.brand ?? prior?.brand ?? null,
    maxBudgetCents:
      next.maxBudgetCents ?? (prior?.maxBudgetCents ?? null),
  };
}

function nullableStr(v: unknown): string | null {
  if (typeof v !== "string") return null;
  const t = v.trim();
  return t.length ? t : null;
}

function nullableInt(v: unknown): number | null {
  if (typeof v !== "number" || !Number.isFinite(v)) return null;
  return Math.max(0, Math.round(v));
}

function truncateTitle(text: string): string {
  const firstLine = text.split(/[\n.!?]/)[0].trim();
  const base = firstLine || text;
  return base.length > 80 ? base.slice(0, 77) + "…" : base;
}

/** Parse a EUR budget from free text into integer cents (best-effort). */
export function parseBudgetCents(text: string): number | null {
  // Look for currency-ish amounts: €1,200 / 1200 EUR / under 500 / 80 euros / $90
  const re =
    /(?:€|eur|euros?|\$|usd)?\s*([0-9]{1,3}(?:[.,][0-9]{3})*(?:[.,][0-9]{1,2})?|[0-9]+(?:[.,][0-9]{1,2})?)\s*(?:€|eur|euros?|bucks?)?/gi;
  let best: number | null = null;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const raw = m[1];
    // skip bare years-ish / tiny noise unless it has a currency cue nearby
    const num = normalizeAmount(raw);
    if (num == null) continue;
    // Heuristic: only treat as budget if the surrounding text hints at money.
    const ctx = text.slice(Math.max(0, m.index - 12), m.index + m[0].length + 6).toLowerCase();
    const hasCue =
      /€|\$|eur|euro|usd|budget|under|below|max|up to|around|about|spend|cost|price|buck/.test(
        ctx,
      );
    if (!hasCue) continue;
    const cents = Math.round(num * 100);
    if (best == null || cents > best) best = cents;
  }
  return best;
}

function normalizeAmount(raw: string): number | null {
  // Handle "1,200" (thousands) vs "1,20" (decimal). Prefer the common DE/EN forms.
  let s = raw;
  const hasComma = s.includes(",");
  const hasDot = s.includes(".");
  if (hasComma && hasDot) {
    // last separator is the decimal point
    if (s.lastIndexOf(",") > s.lastIndexOf(".")) {
      s = s.replace(/\./g, "").replace(",", ".");
    } else {
      s = s.replace(/,/g, "");
    }
  } else if (hasComma) {
    // "1,200" → thousands if 3 digits after, else decimal
    const after = s.split(",")[1] ?? "";
    s = after.length === 3 ? s.replace(",", "") : s.replace(",", ".");
  }
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}
