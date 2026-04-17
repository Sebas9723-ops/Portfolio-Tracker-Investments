import Groq from "groq-sdk";

const API_KEY = process.env.NEXT_PUBLIC_GROQ_API_KEY ?? "";

let _client: Groq | null = null;

export function getGroqClient(): Groq {
  if (!_client) {
    _client = new Groq({ apiKey: API_KEY, dangerouslyAllowBrowser: true });
  }
  return _client;
}

export const GROQ_MODEL = "llama-3.3-70b-versatile";
export const isGroqConfigured = API_KEY.startsWith("gsk_");
