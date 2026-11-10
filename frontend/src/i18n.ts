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
    learning: "Learning", proposals: "Proposals", no_proposals: "No proposals yet.", memory: "Memory",
    remember: "Remember", remember_hint: "Something HomeAI should know", review: "Weekly review",
    rules: "Rules", no_rules: "No rules yet.", rule_add: "Add a rule", rule_name: "Name", rule_entities: "Entities",
    rule_label: "Label id", rule_area: "Area", rule_domain: "Domain", rule_condition: "Condition", rule_minutes: "For at least",
    rule_when: "Active", rule_mode: "Mode", rule_category: "Category", rule_advice: "Advice", rule_enabled: "Enabled",
    rule_preview: "Preview", rule_covers: "Entities covered", rule_meeting: "Meeting it now", rule_off: "off",
    rule_state: "is", rule_not_state: "is not", rule_above: "above", rule_below: "below", rule_unavailable: "unavailable",
    rule_always: "always", rule_night: "at night", rule_away: "nobody home", rule_home: "someone home",
    rule_each: "each entity", rule_all: "all together",
    rule_safety: "Safety", rule_security: "Security", rule_damage: "Damage", rule_system: "System", rule_energy: "Energy",
    rule_comfort: "Comfort", rule_maintenance: "Maintenance", rule_info: "Information",
    rule_nobody: "Nobody", rule_member: "A household member", rule_admin: "An administrator", rule_service: "A technician",
    save: "Save", cancel: "Cancel", edit: "Edit",
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
    learning: "Uczenie", proposals: "Propozycje", no_proposals: "Brak propozycji.", memory: "Pamięć",
    remember: "Zapamiętaj", remember_hint: "Coś, co HomeAI powinno wiedzieć", review: "Przegląd tygodniowy",
    rules: "Reguły", no_rules: "Brak reguł.", rule_add: "Dodaj regułę", rule_name: "Nazwa", rule_entities: "Encje",
    rule_label: "Id etykiety", rule_area: "Obszar", rule_domain: "Domena", rule_condition: "Warunek", rule_minutes: "Przez co najmniej",
    rule_when: "Aktywna", rule_mode: "Tryb", rule_category: "Kategoria", rule_advice: "Rada", rule_enabled: "Włączona",
    rule_preview: "Podgląd", rule_covers: "Objęte encje", rule_meeting: "Spełniają teraz", rule_off: "wyłączona",
    rule_state: "jest", rule_not_state: "nie jest", rule_above: "powyżej", rule_below: "poniżej", rule_unavailable: "niedostępna",
    rule_always: "zawsze", rule_night: "w nocy", rule_away: "nikogo w domu", rule_home: "ktoś w domu",
    rule_each: "każda encja", rule_all: "wszystkie naraz",
    rule_safety: "Bezpieczeństwo", rule_security: "Ochrona", rule_damage: "Szkody", rule_system: "System", rule_energy: "Energia",
    rule_comfort: "Komfort", rule_maintenance: "Konserwacja", rule_info: "Informacja",
    rule_nobody: "Nikt", rule_member: "Domownik", rule_admin: "Administrator", rule_service: "Fachowiec",
    save: "Zapisz", cancel: "Anuluj", edit: "Edytuj",
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
