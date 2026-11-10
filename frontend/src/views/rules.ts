import { LitElement, html, nothing } from "lit";
import { property, state } from "lit/decorators.js";
import { element } from "../define";
import { t } from "../i18n";
import { shared } from "../styles";
import type { HomeAssistant } from "../types";

interface Rule {
  id: string;
  name: string;
  enabled: boolean;
  target: { entities: string[]; label: string | null; area: string | null; domain: string | null };
  condition: { type: string; value?: string | number };
  minutes: number;
  severity: number;
  category: string;
  need: string;
  advice: string;
  when: string;
  mode: string;
  firing?: boolean;
}

const EMPTY: Rule = {
  id: "", name: "", enabled: true, target: { entities: [], label: null, area: null, domain: null },
  condition: { type: "state", value: "on" }, minutes: 10, severity: 1, category: "info", need: "member",
  advice: "", when: "always", mode: "each",
};
const CONDITIONS = ["state", "not_state", "above", "below", "unavailable"];
const CATEGORIES = ["safety", "security", "damage", "system", "energy", "comfort", "maintenance", "info"];
const NEEDS = ["nobody", "member", "admin", "service"];
const WHEN = ["always", "night", "away", "home"];

// Custom detectors without code: the backend validates every rule again on save.
@element("homeai-rules")
export class HomeAIRules extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;
  @state() private rules: Rule[] = [];
  @state() private editing?: Rule;
  @state() private preview?: { covered: { entity_id: string; name: string }[]; meeting: string[] };
  @state() private error = "";

  static styles = shared;

  connectedCallback(): void {
    super.connectedCallback();
    this.load();
  }

  private async load(): Promise<void> {
    const res = await this.hass.callWS<{ rules: Rule[] }>({ type: "homeai/rules/list" });
    this.rules = res.rules;
  }

  private async saveAll(rules: Rule[]): Promise<void> {
    this.error = "";
    try {
      await this.hass.callWS({ type: "homeai/rules/save", rules: rules.map(({ firing, ...r }) => r) });
      this.editing = undefined;
      this.preview = undefined;
      await this.load();
    } catch (err: any) {
      this.error = err?.message ?? String(err);
    }
  }

  private async save(): Promise<void> {
    const rule = this.editing!;
    if (!rule.id) rule.id = rule.name.toLowerCase().normalize("NFD").replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 40) || `rule_${Date.now()}`;
    const others = this.rules.filter((r) => r.id !== rule.id);
    await this.saveAll([...others, rule]);
  }

  private async previewRule(): Promise<void> {
    this.error = "";
    try {
      this.preview = await this.hass.callWS({ type: "homeai/rules/preview", rule: this.editing });
    } catch (err: any) {
      this.error = err?.message ?? String(err);
    }
  }

  private set(path: string, value: unknown): void {
    const rule = structuredClone(this.editing!) as any;
    const keys = path.split(".");
    let node = rule;
    for (const k of keys.slice(0, -1)) node = node[k];
    node[keys[keys.length - 1]] = value;
    this.editing = rule;
  }

  private field(label: string, input: unknown) {
    return html`<label class="row" style="margin: 6px 0"><span style="min-width: 10em">${label}</span><span class="grow">${input}</span></label>`;
  }

  private select(path: string, value: string, options: string[]) {
    return html`<select @change=${(e: Event) => this.set(path, (e.target as HTMLSelectElement).value)}>
      ${options.map((o) => html`<option value=${o} ?selected=${o === value}>${t(this.hass.language, `rule_${o}`)}</option>`)}</select>`;
  }

  private renderEditor() {
    const lang = this.hass.language;
    const r = this.editing!;
    const areas = Object.values((this.hass as any).areas ?? {}) as { area_id: string; name: string }[];
    return html`<div class="card">
      ${this.field(t(lang, "rule_name"), html`<input class="grow" .value=${r.name} @input=${(e: Event) => this.set("name", (e.target as HTMLInputElement).value)} />`)}
      ${this.field(t(lang, "rule_entities"), html`<textarea .value=${r.target.entities.join("\n")} placeholder="sensor.freezer"
        @change=${(e: Event) => this.set("target.entities", (e.target as HTMLTextAreaElement).value.split(/[\n,]/).map((x) => x.trim()).filter(Boolean))}></textarea>`)}
      ${this.field(t(lang, "rule_label"), html`<input .value=${r.target.label ?? ""} @input=${(e: Event) => this.set("target.label", (e.target as HTMLInputElement).value || null)} />`)}
      ${this.field(t(lang, "rule_area"), html`<select @change=${(e: Event) => this.set("target.area", (e.target as HTMLSelectElement).value || null)}>
        <option value="">—</option>${areas.map((a) => html`<option value=${a.area_id} ?selected=${a.area_id === r.target.area}>${a.name}</option>`)}</select>`)}
      ${this.field(t(lang, "rule_domain"), html`<input .value=${r.target.domain ?? ""} placeholder="sensor" @input=${(e: Event) => this.set("target.domain", (e.target as HTMLInputElement).value || null)} />`)}
      ${this.field(t(lang, "rule_condition"), html`${this.select("condition.type", r.condition.type, CONDITIONS)}
        ${r.condition.type === "unavailable" ? nothing : html`<input style="width: 8em" .value=${String(r.condition.value ?? "")}
          @input=${(e: Event) => this.set("condition.value", (e.target as HTMLInputElement).value)} />`}`)}
      ${this.field(t(lang, "rule_minutes"), html`<input type="number" min="0" max="10080" style="width: 6em" .value=${String(r.minutes)}
        @change=${(e: Event) => this.set("minutes", Number((e.target as HTMLInputElement).value))} /> min`)}
      ${this.field(t(lang, "rule_when"), this.select("when", r.when, WHEN))}
      ${this.field(t(lang, "rule_mode"), this.select("mode", r.mode, ["each", "all"]))}
      ${this.field(t(lang, "severity"), html`<input type="number" min="0" max="4" style="width: 4em" .value=${String(r.severity)}
        @change=${(e: Event) => this.set("severity", Number((e.target as HTMLInputElement).value))} />`)}
      ${this.field(t(lang, "rule_category"), this.select("category", r.category, CATEGORIES))}
      ${this.field(t(lang, "who"), this.select("need", r.need, NEEDS))}
      ${this.field(t(lang, "rule_advice"), html`<textarea .value=${r.advice} @change=${(e: Event) => this.set("advice", (e.target as HTMLTextAreaElement).value)}></textarea>`)}
      ${this.field(t(lang, "rule_enabled"), html`<input type="checkbox" .checked=${r.enabled} @change=${(e: Event) => this.set("enabled", (e.target as HTMLInputElement).checked)} />`)}
      ${this.preview ? html`<p class="muted">${t(lang, "rule_covers")}: ${this.preview.covered.length} · ${t(lang, "rule_meeting")}: ${this.preview.meeting.map((id) => this.preview!.covered.find((c) => c.entity_id === id)?.name ?? id).join(", ") || "—"}</p>` : nothing}
      <div class="row">
        <button class="primary" @click=${this.save}>${t(lang, "save")}</button>
        <button @click=${this.previewRule}>${t(lang, "rule_preview")}</button>
        <button @click=${() => { this.editing = undefined; this.preview = undefined; }}>${t(lang, "cancel")}</button>
      </div>
    </div>`;
  }

  render() {
    const lang = this.hass.language;
    if (!this.hass.user.is_admin) return html`<div class="empty">${t(lang, "admin_only")}</div>`;
    return html`
      ${this.error ? html`<div class="card" style="color: var(--error-color)">${this.error}</div>` : nothing}
      ${this.editing ? this.renderEditor() : html`<div class="row" style="margin-bottom: 12px">
        <button class="primary" @click=${() => (this.editing = structuredClone(EMPTY))}>${t(lang, "rule_add")}</button></div>`}
      ${this.rules.length
        ? html`<div class="card"><ul class="plain">${this.rules.map(
            (r) => html`<li class="row"><span class="sev sev-${r.severity}">${r.severity}</span>
              <span class="grow">${r.name}${r.firing ? html` <b>●</b>` : nothing}<br /><span class="muted">${t(lang, `rule_${r.condition.type}`)}${r.condition.type === "unavailable" ? "" : ` ${r.condition.value ?? ""}`} · ${r.minutes} min · ${t(lang, `rule_${r.when}`)}${r.enabled ? "" : ` · ${t(lang, "rule_off")}`}</span></span>
              <button @click=${() => { this.editing = structuredClone(r); this.preview = undefined; }}>${t(lang, "edit")}</button>
              <button @click=${() => this.saveAll(this.rules.filter((x) => x.id !== r.id))}>${t(lang, "remove")}</button></li>`,
          )}</ul></div>`
        : html`<div class="empty">${t(lang, "no_rules")}</div>`}
    `;
  }
}
