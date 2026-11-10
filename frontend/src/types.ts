export interface HassEntity {
  entity_id: string;
  state: string;
  attributes: Record<string, any>;
}

export interface HassUser {
  id: string;
  name: string;
  is_admin: boolean;
}

export interface HomeAssistant {
  language: string;
  user: HassUser;
  states: Record<string, HassEntity>;
  areas?: Record<string, { area_id: string; name: string; floor_id?: string | null }>;
  floors?: Record<string, { floor_id: string; name: string }>;
  devices?: Record<string, { id: string; name: string | null; name_by_user: string | null; area_id: string | null }>;
  callWS<T>(msg: Record<string, unknown>): Promise<T>;
  callService(domain: string, service: string, data?: Record<string, unknown>): Promise<unknown>;
  connection: {
    subscribeMessage<T>(cb: (msg: T) => void, msg: Record<string, unknown>): Promise<() => void>;
  };
}

export interface Situation {
  id: string;
  title: string;
  description: string;
  phase: string;
  kind: string;
  category: string;
  severity: number;
  opened_at: string | null;
  first_seen: string;
  acked_by: string | null;
  handled_by: string | null;
  snoozed_until: string | null;
  assessment: Record<string, any>;
  repair: Record<string, any>;
  entities: string[];
  history: { ts: string; event: string; [k: string]: unknown }[];
}

export interface SettingItem {
  key: string;
  type: string;
  default: unknown;
  section: string;
  group: string;
  scopes: string[];
  min: number | null;
  max: number | null;
  step: number | null;
  unit: string | null;
  options: string[];
  option_labels?: Record<string, string>;
  advanced: boolean;
  confirm: string | null;
  label: string;
  description: string;
  value: unknown;
  source: string;
  overrides: Record<string, unknown>;
}

export interface SettingsSchema {
  language: string;
  sections: { id: string; label: string; description: string }[];
  settings: SettingItem[];
}

export interface JournalEntry {
  id: string;
  ts: string;
  kind: string;
  actor: string;
  text: string;
  result?: string;
}

export interface Approval {
  id: string;
  what: string;
  risk: number;
  reason: string;
  approver: string;
  created: string;
  expires: string;
  status: string;
  decided_by: string | null;
}

export interface WorldSummary {
  floors: { id: string; name: string }[];
  areas: { id: string; name: string; floor_id: string | null }[];
  persons: { id: string; name: string; role: string; home: boolean }[];
}

export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  ts?: string;
}
