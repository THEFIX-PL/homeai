import { LitElement, html, nothing } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import { t } from "../i18n";
import { shared } from "../styles";
import type { HomeAssistant, SettingItem, SettingsSchema } from "../types";

// Every setting is rendered from the backend's registry: adding a setting needs no frontend change.
@customElement("homeai-settings")
export class HomeAISettings extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;
  @state() private schema?: SettingsSchema;
  @state() private section = "general";
  @state() private filter = "";
  @state() private advanced = false;
  @state() private message = "";

  static styles = shared;

  connectedCallback(): void {
    super.connectedCallback();
    this.load();
  }

  private async load(): Promise<void> {
    this.schema = await this.hass.callWS<SettingsSchema>({ type: "homeai/settings/schema", language: this.hass.language });
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
    try {
      let res = await this.hass.callWS<{ needs_confirmation?: boolean; value?: unknown }>({ type: "homeai/settings/set", key: item.key, value });
      if (res.needs_confirmation) {
        if (!confirm(`${item.label}\n\n${t(this.hass.language, "confirm_change")}`)) {
          await this.load();
          return;
        }
        res = await this.hass.callWS({ type: "homeai/settings/set", key: item.key, value, confirmed: true });
      }
      this.message = `${item.label}: ${t(this.hass.language, "saved")}`;
      await this.load();
    } catch (err: any) {
      this.message = err?.message ?? String(err);
      await this.load();
    }
  }

  private async reset(item: SettingItem): Promise<void> {
    await this.hass.callWS({ type: "homeai/settings/reset", key: item.key });
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

  private input(item: SettingItem) {
    const v = item.value;
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
          ${item.options.map((o) => html`<option value=${o} ?selected=${(v as string[]).includes(o)}>${item.option_labels?.[o] ?? o}</option>`)}</select>`;
      case "int": case "float": case "duration":
        return html`<input type="number" style="width: 8em" .value=${String(v)} min=${item.min ?? ""} max=${item.max ?? ""}
          step=${item.step ?? (item.type === "float" ? "any" : 1)} @change=${onChange} /> ${item.unit ?? ""}`;
      case "time":
        return html`<input type="time" .value=${String(v)} @change=${onChange} />`;
      case "json":
        return html`<textarea @change=${onChange}>${JSON.stringify(v, null, 2)}</textarea>`;
      case "entities": case "strings":
        return html`<textarea @change=${onChange} placeholder="one per line">${(v as string[]).join("\n")}</textarea>`;
      case "text":
        return html`<textarea @change=${onChange}>${String(v ?? "")}</textarea>`;
      default:
        return html`<input type="text" .value=${String(v ?? "")} @change=${onChange} />`;
    }
  }

  render() {
    const lang = this.hass.language;
    if (!this.hass.user.is_admin) return html`<div class="empty">${t(lang, "admin_only")}</div>`;
    if (!this.schema) return nothing;
    const q = this.filter.toLowerCase();
    const items = this.schema.settings.filter(
      (s) => (q ? `${s.label} ${s.description} ${s.key}`.toLowerCase().includes(q) : s.section === this.section) && (this.advanced || !s.advanced || q),
    );
    const section = this.schema.sections.find((s) => s.id === this.section);
    return html`
      <div class="row" style="margin-bottom: 12px">
        <input class="grow" type="search" placeholder=${t(lang, "search")} .value=${this.filter} @input=${(e: Event) => (this.filter = (e.target as HTMLInputElement).value)} />
        <label class="row"><input type="checkbox" .checked=${this.advanced} @change=${(e: Event) => (this.advanced = (e.target as HTMLInputElement).checked)} />${t(lang, "advanced")}</label>
        <button @click=${this.undo}>${t(lang, "undo")}</button>
        <button @click=${this.exportSettings}>${t(lang, "export")}</button>
      </div>
      ${q ? nothing : html`<div class="row" style="margin-bottom: 12px">
        ${this.schema.sections.map((s) => html`<button class=${s.id === this.section ? "primary" : ""} @click=${() => (this.section = s.id)}>${s.label}</button>`)}
      </div>
      ${section ? html`<p class="muted">${section.description}</p>` : nothing}`}
      ${this.message ? html`<div class="card muted">${this.message}</div>` : nothing}
      <div class="card">
        ${items.map(
          (item) => html`<div class="row" style="padding: 8px 0; border-bottom: 1px solid var(--divider-color)">
            <div class="grow"><div>${item.label}</div><div class="muted">${item.description}</div>
              ${Object.keys(item.overrides || {}).length ? html`<div class="muted">${Object.keys(item.overrides).length} × ${t(lang, "overridden")}</div>` : nothing}</div>
            <div>${this.input(item)}</div>
            ${item.source !== "default" ? html`<button title=${t(lang, "reset")} @click=${() => this.reset(item)}>↺</button>` : nothing}
          </div>`,
        )}
      </div>`;
  }
}
