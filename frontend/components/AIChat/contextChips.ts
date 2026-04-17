export interface ContextChip {
  label: string;
  prompt: string;
}

const CHIPS: Record<string, ContextChip[]> = {
  "/dashboard": [
    { label: "Portfolio summary", prompt: "Give me an executive summary of my portfolio today — return, critical drift, and most urgent action." },
    { label: "What to do this month?", prompt: "What is the single most important action I should take this month with my portfolio?" },
    { label: "What's driving my return?", prompt: "Which position is contributing most positively and most negatively to my total return?" },
    { label: "When do I hit $100K?", prompt: "At my current contribution pace and historical portfolio return, when do I reach $100K?" },
  ],
  "/rebalancing": [
    { label: "How much to buy this month?", prompt: "I have $250 to deploy. Given the current drift of each position and the Motor 1 constraints, give me the exact USD amount for each ETF." },
    { label: "When will it rebalance?", prompt: "Prioritizing the most underweight ETFs with $250/month, how many months until I reach target weights?" },
    { label: "What to prioritize?", prompt: "Which ETF most urgently needs the next contribution and why?" },
  ],
  "/risk": [
    { label: "Loss in a crash?", prompt: "In a 2008 GFC-style scenario, how much would my portfolio lose in USD and how long would historical recovery take?" },
    { label: "Is my gold enough?", prompt: "With IGLN.L at ~2%, do I have sufficient defensive coverage for my ultra-aggressive profile or should I adjust?" },
    { label: "Interpret my risk", prompt: "Explain my current risk profile in practical terms based on the VaR, CVaR, and stress test results." },
  ],
  "/investment-horizon": [
    { label: "On track for $1M?", prompt: "With my current portfolio and contributions of $250/month + $500 every 6 months, am I on track for $1M before age 50?" },
    { label: "Impact of higher contributions?", prompt: "How many years do I save if I increase monthly contributions from $250 to $500?" },
    { label: "When do I hit $50K?", prompt: "When do I reach the $50K milestone at my current pace?" },
  ],
  "/optimization": [
    { label: "Interpret the results", prompt: "The Max Return frontier suggests these weights. Why did the algorithm choose them and is there anything I should manually override given my ultra-aggressive profile?" },
    { label: "Adjust constraints?", prompt: "Are my current floors and caps optimal for maximizing 15-year returns under an ultra-aggressive mandate?" },
  ],
  "/analytics": [
    { label: "Explain my ratios", prompt: "What do my current ratios (Sharpe, Sortino, Alpha) mean in the context of today's market and my $1M goal?" },
    { label: "Am I diversified?", prompt: "Based on my analytics metrics, do I have real diversification or is there risk concentration I should address?" },
  ],
};

const DEFAULT_CHIPS: ContextChip[] = [
  { label: "Portfolio summary", prompt: "Give me an executive summary of my portfolio today — return, critical drift, and most urgent action." },
  { label: "What to do this month?", prompt: "What is the single most important action I should take this month with my portfolio?" },
];

export function getContextChips(pathname: string): ContextChip[] {
  for (const [route, chips] of Object.entries(CHIPS)) {
    if (pathname === route || pathname.startsWith(route + "/")) return chips;
  }
  return DEFAULT_CHIPS;
}
