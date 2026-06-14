// Phone-number normalization — the ONE place that turns whatever a human (or a
// telephony caller_id) gives us into canonical E.164. Use this everywhere a
// phone is stored or matched so "+49 152 044 46662", "0152 04446662",
// "0049152…", and "+4915204446662" all collapse to the same value.

import { parsePhoneNumberFromString, type CountryCode } from "libphonenumber-js";

// Numbers entered in national format (no country code) are assumed to be from
// this country. Inbound caller_ids from telephony are already E.164 (+…), so the
// default only matters for hand-typed website input. Override via env.
const DEFAULT_COUNTRY = (process.env.DEFAULT_PHONE_COUNTRY || "DE") as CountryCode;

function validE164(p: ReturnType<typeof parsePhoneNumberFromString>): string | null {
  return p && p.isValid() ? p.number : null;
}

/**
 * Normalize to E.164 ("+4915204446662"), or null if it isn't a valid number.
 * Tolerates spaces, dashes, parens, and several "missing +" conventions:
 *   "+49…"        → international, as-is
 *   "0049…"       → "00" international prefix → "+49…"
 *   "0176…"       → national (leading 0) → DEFAULT_COUNTRY
 *   "4917…"       → bare digits that ALREADY include a country code (telephony
 *                   caller_ids and pasted numbers come this way) → read as E.164
 * Telephony caller_ids in particular arrive as E.164 *without* the "+", so we
 * must NOT treat them as national — doing so doubled the country code (the
 * +49…→+4949… bug). Callers MUST treat null as invalid.
 */
export function normalizePhoneE164(raw: string | null | undefined): string | null {
  if (raw == null) return null;
  const s = String(raw).trim();
  if (!s) return null;

  // Explicit international (+…).
  if (s.startsWith("+")) return validE164(parsePhoneNumberFromString(s));

  const digits = s.replace(/\D/g, "");
  if (!digits) return null;

  // "00<cc>…" international dialing prefix.
  if (digits.startsWith("00")) {
    return validE164(parsePhoneNumberFromString("+" + digits.slice(2)));
  }
  // National form (leading single 0) → the default country.
  if (digits.startsWith("0")) {
    return validE164(parsePhoneNumberFromString(digits, DEFAULT_COUNTRY));
  }
  // Bare digits, no leading 0: prefer the E.164-without-"+" reading (the digits
  // already carry a country code — true for caller_ids and pasted numbers); only
  // fall back to a national reading if that isn't a valid number.
  const intl = parsePhoneNumberFromString("+" + digits);
  if (intl && intl.isValid()) return intl.number;
  return validE164(parsePhoneNumberFromString(digits, DEFAULT_COUNTRY));
}

/** True if `raw` normalizes to a valid phone. */
export function isValidPhone(raw: string | null | undefined): boolean {
  return normalizePhoneE164(raw) != null;
}

/** Digits only (no "+"), e.g. for placeholder emails / ids. */
export function phoneDigits(e164: string | null | undefined): string {
  return (e164 ?? "").replace(/\D/g, "");
}

/** Human-friendly international grouping, e.g. "+49 1520 446662". */
export function formatPhoneDisplay(e164: string | null | undefined): string {
  if (!e164) return "";
  const parsed = parsePhoneNumberFromString(e164);
  return parsed ? parsed.formatInternational() : e164;
}
