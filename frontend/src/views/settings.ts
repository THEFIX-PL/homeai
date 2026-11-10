import { LitElement, html, nothing } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import { t, when } from "../i18n";
import { shared } from "../styles";
import type { HomeAssistant, SettingItem, SettingsSchema, WorldSummary } from "../types";

const SCOPES = ["global", "floor", "area", "device", "entity", "person"] as const;
type ScopeType = (typeof SCOPES)[number];

interface Change { ts: string; key: string; scope: string; old: unknown; new: unknown; reset: boolean; user: string | null }

// Every setting is rendered from the backend's registry: adding a setting needs no frontend change.
// A scope (floor, room, device, entity, person) shows only the settings that can be overridden there.
@customElement("homeai-settings")
export class HomeAISettings extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;
  @state() private schema?: SettingsSchema;
  @state() private world?: WorldSummary;
  @state() private section = "general";
  @state() private filter = "";
  @state() private advanced = false;
  @state() private message = "";
  @state() private scopeType: ScopeType = "global";
  @state() private scopeRef = "";
  @state() private scopeValues: Record<string, unknown> = {};
  @state() private history?: Change[];

  static styles = shared;

  connectedCallback(): void {
    super.connectedCallback();
    this.load();
  }

  private get skey(): string {
    return this.scopeType === "global" || !this.scopeRef ? "global" : `${this.scopeType}:${this.scopeRef}`;
  }

  private async load(): Promise<void> {
    this.schema = await this.hass.callWS<SettingsSchema>({ type: "homeai/settings/schema", language: this.hass.language });
    if (!this.world) this.world = await this.hass.callWS<WorldSummary>({ type: "homeai/world/summary" });
    await this.loadScope();
  }

  private async loadScope(): Promise<void> {
    if (this.skey === "global") {
      this.scopeValues = {};
      return;
    }
    const res = await this.hass.callWS<{ values: Record<string, unknown> }>({ type: "homeai/settings/scope", scope: this.skey });
    this.scopeValues = res.values;
  }

  private targets(): { id: string; name: string }[] {
    const hass = this.hass;
    switch (this.scopeType) {
      case "floor": return (this.world?.floors ?? []).map((f) => ({ id: f.id, name: f.name }));
      case "area": return (this.world?.areas ?? []).map((a) => ({ id: a.id, name: a.name }));
      case "person": return (this.world?.persons ?? []).map((p) => ({ id: p.id, name: p.name }));
      case "device":
        return Object.values(hass.devices ?? {})
          .map((d) => ({ id: d.id, name: d.name_by_user || d.name || d.id }))
          .sort((a, b) => a.name.localeCompare(b.name));
      case "entity":
        return Object.values(hass.states)
          .map((s) => ({ id: s.entity_id, name: `${s.attributes.friendly_name ?? s.entity_id} (${s.entity_id})` }))
          .sort((a, b) => a.name.localeCompare(b.name));
      default: return [];
    }
  }

  private parse(item: SettingItem, raw: string | boolean | string[]): unknown {
    switch (item.type) {
      case "bool": return Boolean(raw);
      case "int": case "duration": return parseInt(String(raw), 10);
      case "float": return parseFloat(String(raw));
      case "multiselect": return raw;
      case "entities": case "strings": return String(raw).split(/[\n,]/).map((x) => x.trim()).filter(Boolean);
      case "json": return JSON.parse(String(raw));
      default: return raw;
    }
  }

  private async save(item: SettingItem, raw: string | boolean | string[]): Promise<void> {
    let value: unknown;
    try {
      value = this.parse(item, raw);
    } catch (err) {
      this.message = `${item.label}: ${err}`;
      return;
    }
    const scope = this.skey;
    try {
      const res = await this.hass.callWS<{ needs_confirmation?: boolean }>({ type: "homeai/settings/set", key: item.key, value, scope });
      if (res.needs_confirmation) {
        if (!confirm(`${item.label}\n\n${t(this.hass.language, "confirm_change")}`)) {
          await this.load();
          return;
        }
        await this.hass.callWS({ type: "homeai/settings/set", key: item.key, value, scope, confirmed: true });
      }
      this.message = `${item.label}: ${t(this.hass.language, "saved")}`;
    } catch (err: any) {
      this.message = err?.message ?? String(err);
    }
    await this.load();
  }

  private async reset(item: SettingItem): Promise<void> {
    await this.hass.callWS({ type: "homeai/settings/reset", key: item.key, scope: this.skey });
    await this.load();
  }

  private async resetSection(): Promise<void> {
    const section = this.schema?.sections.find((s) => s.id === this.section);
    if (!section || !confirm(`${section.label}\n\n${t(this.hass.language, "reset_section_confirm")}`)) return;
    const res = await this.hass.callWS<{ reset: number }>({ type: "homeai/settings/reset_section", section: this.section });
    this.message = `${section.label}: ${res.reset} × ${t(this.hass.language, "reset")}`;
    await this.load();
  }

  private async undo(): Promise<void> {
    await this.hass.callWS({ type: "homeai/settings/undo" });
    await this.load();
  }

  private async exportSettings(): Promise<void> {
    const data = await this.hass.callWS({ type: "homeai/settings/export" });
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "homeai-settings.json";
    a.click();
  }

  private async importSettings(e: Event): Promise<void> {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = "";
    if (!file || !confirm(t(this.hass.language, "import_confirm"))) return;
    try {
      const data = JSON.parse(await file.text());
      const res = await this.hass.callWS<{ changed: number }>({ type: "homeai/settings/import", data });
      this.message = `${t(this.hass.language, "import")}: ${res.changed}`;
    } catch (err: any) {
      this.message = err?.message ?? String(err);
    }
    await this.load();
  }

  private async toggleHistory(): Promise<void> {
    if (this.history) {
      this.history = undefined;
      return;
    }
    const res = await this.hass.callWS<{ history: Change[] }>({ type: "homeai/settings/history", limit: 100 });
    this.history = res.history;
  }

  private input(item: SettingItem, v: unknown) {
    const onChange = (e: Event) => {
      const el = e.target as HTMLInputElement & HTMLSelectElement & HTMLTextAreaElement;
      if (item.type === "bool") return this.save(item, el.checked);
      if (item.type === "multiselect") return this.save(item, Array.from(el.selectedOptions).map((o) => o.value));
      return this.save(item, el.value);
    };
    switch (item.type) {
      case "bool":
        return html`<input type="checkbox" .checked=${Boolean(v)} @change=${onChange} />`;
      case "select":
        return html`<select @change=${onChange}>${item.options.map((o) => html`<option value=${o} ?selected=${o === v}>${item.option_labels?.[o] ?? o}</option>`)}</select>`;
      case "multiselect":
        return html`<select multiple size=${Math.min(item.options.length, 6)} @change=${onChange}>
          ${item.options.map((o) => html`<option value=${o} ?selected=${((v as string[]) ?? []).includes(o)}>${item.option_labels?.[o] ?? o}</option>`)}</select>`;
      case "int": case "float": case "duration":
        return html`<input type="number" style="width: 8em" .value=${String(v)} min=${item.min ?? ""} max=${item.max ?? ""}
          step=${item.step ?? (item.type === "float" ? "any" : 1)} @change=${onChange} /> ${item.unit ?? ""}`;
      case "time":
        return html`<input type="time" .value=${String(v)} @change=${onChange} />`;
      case "json":
        return html`<textarea @change=${onChange}>${JSON.stringify(v, null, 2)}</textarea>`;
      case "entities": case "strings":
        return html`<textarea @change=${onChange} placeholder="one per line">${((v as string[]) ?? []).join("\n")}</textarea>`;
      case "text":
        return html`<textarea @change=${onChange}>${String(v ?? "")}</textarea>`;
      default:
        return html`<input type="text" .value=${String(v ?? "")} @change=${onChange} />`;
    }
  }

  private scopeBar() {
    const lang = this.hass.language;
    const targets = this.targets();
    return html`<div class="row" style="margin-bottom: 12px">
      <span class="muted">${t(lang, "scope")}</span>
      <select @change=${(e: Event) => {
        this.scopeType = (e.target as HTMLSelectElement).value as ScopeType;
        this.scopeRef = "";
        this.loadScope();
      }}>${SCOPES.map((s) => html`<option value=${s} ?selected=${s === this.scopeType}>${t(lang, `scope_${s}`)}</option>`)}</select>
      ${this.scopeType === "global" ? nothing : html`<select class="grow" @change=${(e: Event) => {
        this.scopeRef = (e.target as HTMLSelectElement).value;
        this.loadScope();
      }}><option value="">—</option>${targets.map((x) => html`<option value=${x.id} ?selected=${x.id === this.scopeRef}>${x.name}</option>`)}</select>`}
    </div>`;
  }

  private historyCard() {
    const lang = this.hass.language;
    const labels = new Map((this.schema?.settings ?? []).map((s) => [s.key, s.label]));
    const show = (v: unknown) => (v === null || v === undefined ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v));
    return html`<div class="card"><div class="title">${t(lang, "history")}</div><ul class="plain">
      ${(this.history ?? []).map((c) => html`<li><div class="row"><span class="muted">${when(c.ts, lang)}</span>
        <span class="grow">${labels.get(c.key) ?? c.key}${c.scope !== "global" ? html` <span class="muted">(${c.scope})</span>` : nothing}</span>
        <span class="muted">${c.user ?? ""}</span></div>
        <div class="muted">${c.key === "import" ? t(lang, "import") : c.reset ? `${show(c.old)} → ${t(lang, "default")}` : `${show(c.old)} → ${show(c.new)}`}</div></li>`)}
    </ul></div>`;
  }

  render() {
    const lang = this.hass.language;
    if (!this.hass.user.is_admin) return html`<div class="empty">${t(lang, "admin_only")}</div>`;
    if (!this.schema) return nothing;
    const q = this.filter.toLowerCase();
    const scoped = this.skey !== "global";
    const items = this.schema.settings.filter(
      (s) =>
        (q ? `${s.label} ${s.description} ${s.key}`.toLowerCase().includes(q) : s.section === this.section) &&
        (this.advanced || !s.advanced || q) &&
        (this.scopeType === "global" || s.scopes.includes(this.scopeType)),
    );
    const section = this.schema.sections.find((s) => s.id === this.section);
    return html`
      <div class="row" style="margin-bottom: 12px">
        <input class="grow" type="search" placeholder=${t(lang, "search")} .value=${this.filter} @input=${(e: Event) => (this.filter = (e.target as HTMLInputElement).value)} />
        <label class="row"><input type="checkbox" .checked=${this.advanced} @change=${(e: Event) => (this.advanced = (e.target as HTMLInputElement).checked)} />${t(lang, "advanced")}</label>
        <button @click=${this.undo}>${t(lang, "undo")}</button>
        <button @click=${this.toggleHistory}>${t(lang, "history")}</button>
        <button @click=${this.exportSettings}>${t(lang, "export")}</button>
        <span><button @click=${(e: Event) => ((e.currentTarget as HTMLElement).nextElementSibling as HTMLInputElement).click()}>${t(lang, "import")}</button><input type="file" accept="application/json,.json" hidden @change=${this.importSettings} /></span>
      </div>
      ${this.scopeBar()}
      ${this.history ? this.historyCard() : nothing}
      ${q ? nothing : html`<div class="row" style="margin-bottom: 12px">
        ${this.schema.sections.map((s) => html`<button class=${s.id === this.section ? "primary" : ""} @click=${() => (this.section = s.id)}>${s.label}</button>`)}
      </div>
      ${section ? html`<div class="row"><p class="muted grow">${section.description}</p>
        ${scoped ? nothing : html`<button @click=${this.resetSection}>${t(lang, "reset_section")}</button>`}</div>` : nothing}`}
      ${this.message ? html`<div class="card muted">${this.message}</div>` : nothing}
      ${this.scopeType !== "global" && !this.scopeRef ? html`<div class="empty">${t(lang, "scope_pick")}</div>` : html`<div class="card">
        ${items.length ? nothing : html`<div class="muted">${t(lang, "scope_none")}</div>`}
        ${items.map((item) => {
          const here = scoped && item.key in this.scopeValues;
          const value = here ? this.scopeValues[item.key] : item.value;
          const count = Object.keys(item.overrides || {}).length;
          return html`<div class="row" style="padding: 8px 0; border-bottom: 1px solid var(--divider-color)">
            <div class="grow"><div>${item.label}</div><div class="muted">${item.description}</div>
              ${here ? html`<div class="muted"><b>${t(lang, "overridden")}</b></div>`
                : scoped ? html`<div class="muted">${t(lang, "inherited")}</div>`
                : count ? html`<div class="muted">${count} × ${t(lang, "overridden")}</div>` : nothing}</div>
            <div>${this.input(item, value)}</div>
            ${(scoped ? here : item.source !== "default") ? html`<button title=${t(lang, "reset")} @click=${() => this.reset(item)}>↺</button>` : nothing}
          </div>`;
        })}
      </div>`}`;
  }
}
