export const runtime = "nodejs";
import { NextResponse } from "next/server";

export async function GET() {
  const groqKey = process.env.GROQ_API_KEY;
  const groqKeyPublic = process.env.NEXT_PUBLIC_GROQ_API_KEY;
  return NextResponse.json({
    GROQ_API_KEY: groqKey ? `SET (starts with: ${groqKey.slice(0, 8)}...)` : "NOT SET",
    NEXT_PUBLIC_GROQ_API_KEY: groqKeyPublic ? `SET (starts with: ${groqKeyPublic.slice(0, 8)}...)` : "NOT SET",
    NODE_ENV: process.env.NODE_ENV,
  });
}
