// Brevo (ex-Sendinblue) transactional email — the one place we talk to the
// Brevo SMTP API. Used for magic-link sign-in, invites, escalation notices,
// and completion receipts. Auth via the `api-key` header (NOT a Bearer token).

const BREVO_API_URL = "https://api.brevo.com/v3/smtp/email";

export interface SendEmailParams {
  to: string;
  subject: string;
  html: string;
  /** Optional plain-text fallback. */
  text?: string;
  /** Override the default sender for this one message. */
  senderEmail?: string;
  senderName?: string;
}

export interface SendEmailResult {
  /** Brevo's transactional message id, when the API returns one. */
  messageId?: string;
}

/**
 * Send one transactional email through Brevo.
 * Throws if BREVO_API_KEY is missing or the API responds non-2xx.
 */
export async function sendEmail(params: SendEmailParams): Promise<SendEmailResult> {
  const apiKey = process.env.BREVO_API_KEY;
  if (!apiKey) throw new Error("BREVO_API_KEY is not set");

  const senderEmail =
    params.senderEmail ?? process.env.BREVO_SENDER_EMAIL ?? "no-reply@sivra.io";
  const senderName = params.senderName ?? "sivra";

  const res = await fetch(BREVO_API_URL, {
    method: "POST",
    headers: {
      "api-key": apiKey,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({
      sender: { email: senderEmail, name: senderName },
      to: [{ email: params.to }],
      subject: params.subject,
      htmlContent: params.html,
      ...(params.text ? { textContent: params.text } : {}),
    }),
  });

  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`Brevo send failed (${res.status}): ${detail}`);
  }

  const data = (await res.json().catch(() => ({}))) as { messageId?: string };
  return { messageId: data.messageId };
}
