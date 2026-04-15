"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { login } from "@/lib/api/auth";
import { useAuthStore } from "@/lib/store/authStore";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const doLogin = useAuthStore((s) => s.login);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const res = await login(email, password);
      doLogin(res.access_token, res.user_id, res.email);
      router.push("/dashboard");
    } catch {
      setError("Invalid credentials. Check your email and password.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: "#0b0f14" }}>
      <div className="bbg-card w-80">
        <h1 className="text-bloomberg-gold text-sm font-bold tracking-widest uppercase mb-6">
          PORTFOLIO TRACKER
        </h1>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase tracking-widest mb-1">
              Email
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-3 py-1.5 text-xs focus:outline-none focus:border-bloomberg-gold"
              required
            />
          </div>
          <div>
            <label className="block text-bloomberg-muted text-[10px] uppercase tracking-widest mb-1">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-bloomberg-bg border border-bloomberg-border text-bloomberg-text px-3 py-1.5 text-xs focus:outline-none focus:border-bloomberg-gold"
              required
            />
          </div>
          {error && <p className="text-bloomberg-red text-xs">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-bloomberg-gold text-bloomberg-bg font-bold text-xs py-2 tracking-widest uppercase hover:bg-bloomberg-gold-dim disabled:opacity-50"
          >
            {loading ? "SIGNING IN..." : "SIGN IN"}
          </button>
        </form>
      </div>
    </div>
  );
}
