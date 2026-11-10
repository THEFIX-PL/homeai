// Panel texts. Messages from HomeAI itself (titles, journal) arrive already translated by the backend.
const TEXTS: Record<string, Record<string, string>> = {
  en: {
    situations: "Situations", approvals: "Approvals", plan: "Plan", journal: "Journal", settings: "Settings", ai: "AI",
    nothing_open: "Nothing needs attention.", ack: "Got it", handle: "I'll handle it", snooze: "Snooze",
    dismiss: "Not a problem", severity: "Severity", who: "Who", repairing: "HomeAI is fixing it",
    approve: "Approve", deny: "Deny", no_approvals: "No requests waiting.", expires: "expires",
    no_plan: "The plan is empty.", remove: "Remove", search: "Search settings", advanced: "Show advanced",
    reset: "Reset", saved: "Saved", confirm_change: "This lowers protection or changes something important. Continue?",
    overridden: "overridden here", default: "default", undo: "Undo last change", export: "Export", import: "Import",
    cost_today: "Cost today", cost_month: "This month", tiers: "Tiers", no_tiers: "No AI tier yet. Add one in the integration's settings (Add AI tier).",
    last_prompt: "Last request", resolved: "Recently resolved", admin_only: "Only administrators can change settings.",
    since: "since", reason: "Why", steps: "Steps",
  },
  pl: {
    situations: "Sprawy", approvals: "Zgody", plan: "Plan", journal: "Dziennik", settings: "Ustawienia", ai: "AI",
    nothing_open: "Nic nie wymaga uwagi.", ack: "Wiem", handle: "Zajmę się", snooze: "Wycisz",
    dismiss: "To nie problem", severity: "Waga", who: "Kto", repairing: "HomeAI naprawia",
    approve: "Zgoda", deny: "Odmowa", no_approvals: "Brak oczekujących próśb.", expires: "wygasa",
    no_plan: "Plan jest pusty.", remove: "Usuń", search: "Szukaj ustawień", advanced: "Pokaż zaawansowane",
    reset: "Przywróć", saved: "Zapisano", confirm_change: "To obniża ochronę albo zmienia coś ważnego. Kontynuować?",
    overridden: "nadpisane tutaj", default: "domyślnie", undo: "Cofnij ostatnią zmianę", export: "Eksport", import: "Import",
    cost_today: "Koszt dziś", cost_month: "W tym miesiącu", tiers: "Poziomy", no_tiers: "Brak poziomu AI. Dodaj go w ustawieniach integracji (Dodaj poziom AI).",
    last_prompt: "Ostatnie zapytanie", resolved: "Ostatnio rozwiązane", admin_only: "Ustawienia zmieniają tylko administratorzy.",
    since: "od", reason: "Dlaczego", steps: "Kroki",
  },
};

export function t(lang: string, key: string): string {
  const base = (lang || "en").split("-")[0];
  return TEXTS[base]?.[key] ?? TEXTS.en[key] ?? key;
}

export function when(iso: string | null | undefined, lang: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString(lang, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
