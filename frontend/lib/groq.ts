import Groq from "groq-sdk";

export const groqClient = new Groq({
  apiKey: process.env.NEXT_PUBLIC_GROQ_API_KEY ?? "",
  dangerouslyAllowBrowser: true,
});

export const GROQ_MODEL = "llama-3.3-70b-versatile";
export const isGroqConfigured = !!process.env.NEXT_PUBLIC_GROQ_API_KEY;
