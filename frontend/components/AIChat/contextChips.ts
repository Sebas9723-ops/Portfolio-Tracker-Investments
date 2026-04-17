export interface ContextChip {
  label: string;
  prompt: string;
}

const CHIPS: Record<string, ContextChip[]> = {
  "/dashboard": [
    { label: "¿Cómo va mi portfolio?", prompt: "Dame un resumen ejecutivo de mi portfolio hoy — retorno, drift crítico y acción más urgente." },
    { label: "¿Qué hago este mes?", prompt: "¿Cuál es la acción más importante que debo tomar este mes con mi portfolio?" },
    { label: "¿Qué mueve mi retorno?", prompt: "¿Qué posición contribuye más positiva y negativamente a mi retorno total?" },
    { label: "¿Cuándo llego a $100K?", prompt: "Con mi ritmo actual de aportes y el retorno histórico de mi portfolio, ¿cuándo llego a $100K?" },
  ],
  "/rebalancing": [
    { label: "¿Cuánto compro este mes?", prompt: "Tengo $250 para aportar. Con el drift actual de cada posición y los constraints del Motor 1, dame el monto exacto en USD para cada ETF." },
    { label: "¿Cuándo se equilibra?", prompt: "Priorizando los ETFs más subpesados con $250/mes, ¿en cuántos meses llego a los weights objetivo?" },
    { label: "¿Qué priorizo?", prompt: "¿Qué ETF necesita más urgentemente el próximo aporte y por qué?" },
  ],
  "/risk": [
    { label: "¿Cuánto perdería en crash?", prompt: "En un escenario tipo 2008 GFC, ¿cuánto perdería mi portfolio en USD y en cuánto tiempo me recuperaría históricamente?" },
    { label: "¿Es suficiente mi oro?", prompt: "Con IGLN.L al 2%, ¿tengo suficiente cobertura defensiva para mi perfil ultra-agresivo o debería ajustar?" },
    { label: "Interpreta mi riesgo", prompt: "Explícame en términos prácticos mi perfil de riesgo actual basándote en el VaR, CVaR y stress tests." },
  ],
  "/investment-horizon": [
    { label: "¿Voy bien para $1M?", prompt: "Con mi portfolio actual y aportes de $250/mes + $500 cada 6 meses, ¿voy en camino a $1M antes de los 50?" },
    { label: "¿Qué pasa si aporto más?", prompt: "¿Cuántos años me ahorro si subo el aporte de $250 a $500 mensuales?" },
    { label: "¿Cuándo llego a $50K?", prompt: "¿Cuándo llego al hito de $50K con mi ritmo actual?" },
  ],
  "/optimization": [
    { label: "Interpreta los resultados", prompt: "El Max Return sugiere estos weights. ¿Por qué el algoritmo los eligió y hay algo que debería overridear manualmente dado mi perfil ultra-agresivo?" },
    { label: "¿Debo ajustar los constraints?", prompt: "¿Los floors y caps que tengo configurados son óptimos para maximizar retorno a 15 años con perfil ultra agresivo?" },
  ],
  "/analytics": [
    { label: "Explícame mis ratios", prompt: "¿Qué significan mis ratios actuales (Sharpe, Sortino, Alpha) en contexto del mercado actual y mi objetivo de $1M?" },
    { label: "¿Estoy bien diversificado?", prompt: "Basándote en mis métricas de analytics, ¿tengo diversificación real o hay concentración de riesgo que deba corregir?" },
  ],
};

const DEFAULT_CHIPS: ContextChip[] = [
  { label: "¿Cómo va mi portfolio?", prompt: "Dame un resumen ejecutivo de mi portfolio hoy — retorno, drift crítico y acción más urgente." },
  { label: "¿Qué hago este mes?", prompt: "¿Cuál es la acción más importante que debo tomar este mes con mi portfolio?" },
];

export function getContextChips(pathname: string): ContextChip[] {
  // Match exact route or parent route
  for (const [route, chips] of Object.entries(CHIPS)) {
    if (pathname === route || pathname.startsWith(route + "/")) return chips;
  }
  return DEFAULT_CHIPS;
}
