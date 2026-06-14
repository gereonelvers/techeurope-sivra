// Dispatch — the one place apps/web reaches out to a human about an escalation.
// Three channels: SMS (Telnyx REST), Voice (the elevenlabs-voice service), and
// Email (Brevo, via lib/brevo). notifyEscalation() picks the channel by the
// escalation's urgency tier and ALWAYS includes the tokenized /d/:code reply link.
//
// DISPATCH_DRY_RUN: when set (truthy), every outbound side-effect is logged
// instead of actually sent/called. Tests run with DISPATCH_DRY_RUN=1.

import { sendEmail } from "@/lib/brevo";

function dryRun(): boolean {
  const v = process.env.DISPATCH_DRY_RUN;
  return v !== undefined && v !== "" && v !== "0" && v.toLowerCase() !== "false";
}

/** App base URL for reply links — AUTH_URL in dev, sivra.io fallback. */
export function appBaseUrl(): string {
  return (process.env.AUTH_URL ?? "https://sivra.io").replace(/\/$/, "");
}

/** Public tokenized reply link for an escalation code. */
export function replyLink(code: string): string {
  return `${appBaseUrl()}/d/${code}`;
}

export interface DispatchResult {
  channel: "email" | "sms" | "voice" | "none";
  ok: boolean;
  dryRun: boolean;
  detail?: string;
}

// ── SMS via Telnyx REST ────────────────────────────────────────────────────────
const TELNYX_URL = "https://api.telnyx.com/v2/messages";

/**
 * Send an SMS via Telnyx. Prefers the alpha sender (TELNYX_ALPHA_SENDER) for
 * US→DE deliverability when present, else the numeric TELNYX_FROM. Honors
 * DISPATCH_DRY_RUN. Never throws — returns a DispatchResult.
 */
export async function sendSms(to: string, text: string): Promise<DispatchResult> {
  if (dryRun()) {
    console.log(`[dispatch:dry-run] SMS → ${to}: ${text}`);
    return { channel: "sms", ok: true, dryRun: true };
  }
  const apiKey = process.env.TELNYX_API_KEY;
  if (!apiKey) {
    console.warn("[dispatch] TELNYX_API_KEY not set — skipping SMS");
    return { channel: "sms", ok: false, dryRun: false, detail: "no TELNYX_API_KEY" };
  }
  const from = process.env.TELNYX_ALPHA_SENDER || process.env.TELNYX_FROM;
  const messagingProfileId = process.env.TELNYX_MESSAGING_PROFILE_ID;
  const body: Record<string, unknown> = { to, text };
  if (from) body.from = from;
  if (messagingProfileId) body.messaging_profile_id = messagingProfileId;
  try {
    const res = await fetch(TELNYX_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      console.warn(`[dispatch] Telnyx SMS failed (${res.status}): ${detail}`);
      return { channel: "sms", ok: false, dryRun: false, detail };
    }
    return { channel: "sms", ok: true, dryRun: false };
  } catch (err) {
    console.warn("[dispatch] Telnyx SMS error:", err);
    return { channel: "sms", ok: false, dryRun: false, detail: String(err) };
  }
}

// ── Voice via the elevenlabs-voice service ─────────────────────────────────────
export interface PlaceVoiceCallParams {
  requestId: string;
  to: string;
  context: string;
  person?: string;
}

/**
 * Place an outbound escalation call through the elevenlabs-voice service
 * (POST {ELEVENLABS_VOICE_URL}/call). Honors DISPATCH_DRY_RUN. Never throws.
 */
export async function placeVoiceCall(
  params: PlaceVoiceCallParams,
): Promise<DispatchResult> {
  if (dryRun()) {
    console.log(
      `[dispatch:dry-run] VOICE call → ${params.to} (req ${params.requestId}): ${params.context}`,
    );
    return { channel: "voice", ok: true, dryRun: true };
  }
  const base = process.env.ELEVENLABS_VOICE_URL;
  if (!base) {
    console.warn("[dispatch] ELEVENLABS_VOICE_URL not set — skipping voice call");
    return { channel: "voice", ok: false, dryRun: false, detail: "no ELEVENLABS_VOICE_URL" };
  }
  try {
    const res = await fetch(`${base.replace(/\/$/, "")}/call`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        request_id: params.requestId,
        to: params.to,
        context: params.context,
        person: params.person ?? null,
      }),
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      console.warn(`[dispatch] voice /call failed (${res.status}): ${detail}`);
      return { channel: "voice", ok: false, dryRun: false, detail };
    }
    return { channel: "voice", ok: true, dryRun: false };
  } catch (err) {
    console.warn("[dispatch] voice /call error:", err);
    return { channel: "voice", ok: false, dryRun: false, detail: String(err) };
  }
}

// ── Email via Brevo ────────────────────────────────────────────────────────────
function escalationEmail(opts: {
  message: string;
  link: string;
  orderTitle?: string | null;
}) {
  const { message, link, orderTitle } = opts;
  const subject = orderTitle
    ? `Approval needed: ${orderTitle}`
    : "A purchase needs your sign-off";
  const html = `
  <div style="background:#F4F2EB;padding:40px 0;font-family:Inter,system-ui,-apple-system,sans-serif;color:#211f1a;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
      <tr><td align="center">
        <table role="presentation" width="520" cellpadding="0" cellspacing="0"
          style="background:#ffffff;border:1px solid #e6e2d6;border-radius:14px;padding:36px;">
          <tr><td>
            <img src="https://sivra.io/sivra-wordmark.png" alt="sivra" width="104" style="display:block;height:auto;margin:0 0 12px;" />
            <p style="font-size:15px;line-height:1.6;margin:0 0 20px;color:#4a463f;">${escapeHtml(message)}</p>
            <a href="${link}"
              style="display:inline-block;background:#3A357C;color:#ffffff;text-decoration:none;
                     padding:13px 28px;border-radius:10px;font-size:15px;font-weight:600;">
              Review &amp; respond
            </a>
            <p style="font-size:13px;line-height:1.6;margin:28px 0 0;color:#8a857a;">
              This link is unique to this request. Approve, counter, or decline in one click.
            </p>
          </td></tr>
        </table>
      </td></tr>
    </table>
  </div>`;
  const text = `${message}\n\nReview & respond: ${link}`;
  return { subject, html, text };
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function sendEscalationEmail(
  to: string,
  message: string,
  link: string,
  orderTitle?: string | null,
): Promise<DispatchResult> {
  if (dryRun()) {
    console.log(`[dispatch:dry-run] EMAIL → ${to}: ${message} (${link})`);
    return { channel: "email", ok: true, dryRun: true };
  }
  try {
    const { subject, html, text } = escalationEmail({ message, link, orderTitle });
    await sendEmail({ to, subject, html, text });
    return { channel: "email", ok: true, dryRun: false };
  } catch (err) {
    console.warn("[dispatch] escalation email error:", err);
    return { channel: "email", ok: false, dryRun: false, detail: String(err) };
  }
}

// ── notifyEscalation — channel selection by urgency ────────────────────────────

/** Minimal shape notifyEscalation needs from an Escalation row. */
export interface NotifiableEscalation {
  code: string;
  requestId: string;
  urgencyTier: string; // "ASYNC" | "URGENT_PUSH" | "VOICE" (Prisma enum) or lowercase
  suggestedMessage?: string | null;
  situationText?: string | null;
  orderTitle?: string | null;
  targetPurchasingRole?: string | null;
}

/** Minimal shape of the resolved target member. */
export interface NotifiableMember {
  email?: string | null;
  phone?: string | null;
  name?: string | null;
}

function normalizeTier(tier: string): "async" | "urgent_push" | "voice" {
  const t = (tier || "").toLowerCase();
  if (t === "voice") return "voice";
  if (t === "urgent_push" || t === "urgent") return "urgent_push";
  return "async";
}

/**
 * Notify the resolved target member about an escalation, picking the channel by
 * urgency:
 *   async       → email with the /d/:code link
 *   urgent_push → SMS with the link
 *   voice       → outbound voice call + SMS link as backup
 * The reply link is ALWAYS included. Returns the attempts made (one or two).
 * Never throws — dispatch is best-effort; the audit row is the source of truth.
 */
export async function notifyEscalation(
  escalation: NotifiableEscalation,
  targetMember: NotifiableMember | null,
): Promise<DispatchResult[]> {
  const tier = normalizeTier(escalation.urgencyTier);
  const link = replyLink(escalation.code);
  const message =
    escalation.suggestedMessage?.trim() ||
    escalation.situationText?.trim() ||
    "A purchase needs your sign-off.";
  const email = targetMember?.email ?? null;
  const phone = targetMember?.phone ?? null;
  const person = targetMember?.name ?? escalation.targetPurchasingRole ?? undefined;

  const smsText = `sivra: ${truncate(message, 240)} Reply: ${link}`;
  const results: DispatchResult[] = [];

  if (tier === "voice") {
    if (phone) {
      results.push(
        await placeVoiceCall({
          requestId: escalation.requestId,
          to: phone,
          context: message,
          person,
        }),
      );
      // SMS link backup so they can also act asynchronously.
      results.push(await sendSms(phone, smsText));
    } else if (email) {
      results.push(await sendEscalationEmail(email, message, link, escalation.orderTitle));
    } else {
      console.warn("[dispatch] voice escalation but target has no phone/email");
      results.push({ channel: "none", ok: false, dryRun: dryRun(), detail: "no contact" });
    }
    return results;
  }

  if (tier === "urgent_push") {
    if (phone) {
      results.push(await sendSms(phone, smsText));
    } else if (email) {
      results.push(await sendEscalationEmail(email, message, link, escalation.orderTitle));
    } else {
      results.push({ channel: "none", ok: false, dryRun: dryRun(), detail: "no contact" });
    }
    return results;
  }

  // async → email (fall back to SMS if no email but we have a phone)
  if (email) {
    results.push(await sendEscalationEmail(email, message, link, escalation.orderTitle));
  } else if (phone) {
    results.push(await sendSms(phone, smsText));
  } else {
    results.push({ channel: "none", ok: false, dryRun: dryRun(), detail: "no contact" });
  }
  return results;
}

function truncate(s: string, n: number): string {
  return s.length <= n ? s : s.slice(0, n - 1) + "…";
}
