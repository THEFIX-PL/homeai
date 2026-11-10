import { LitElement, html, nothing } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import { t, when } from "../i18n";
import { shared } from "../styles";
import type { HomeAssistant, WorldSummary } from "../types";

interface Item { id: string; kind: string; person: string | null; start: string; end: string; note: string }
interface Draft { id?: string; kind: string; person: string; start: string; end: string; note: string }

const KINDS = ["away", "vacation", "guests", "home_office", "sick"];

function day(offset = 0): string {
  const d = new Date(Date.now() + offset * 86400000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function localDay(iso: string, end = false): string {
  // Stored ends are exclusive (midnight after the last day); show the last day itself.
  const d = new Date(new Date(iso).getTime() - (end ? 1000 : 0));
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// Trips, guests, working from home: exceptions HomeAI and every automation can read from calendar.homeai_presence.
@customElement("homeai-presence")
export class HomeAIPresence extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;
  @state() private items: Item[] = [];
  @state() private world?: WorldSummary;
  @state() private draft?: Draft;
  @state() private error = "";

  static styles = shared;

  connectedCallback(): void {
    super.connectedCallback();
    this.load();
  }

  private async load(): Promise<void> {
    const res = await this.hass.callWS<{ items: Item[] }>({ type: "homeai/presence/list", days: 120 });
    this.items = res.items.sort((a, b) => a.start.localeCompare(b.start));
    if (!this.world) this.world = await this.hass.callWS<WorldSummary>({ type: "homeai/world/summary" });
  }

  private personName(id: string | null): string {
    if (!id) return t(this.hass.language, "presence_everyone");
    return this.world?.persons.find((p) => p.id === id)?.name ?? id;
  }

  private async save(): Promise<void> {
    const d = this.draft!;
    const item = { kind: d.kind, person: d.person || null, start: d.start, end: d.end, note: d.note };
    try {
      await this.hass.callWS({ type: "homeai/presence/save", item, ...(d.id ? { exception_id: d.id } : {}) });
      this.draft = undefined;
      this.error = "";
      await this.load();
    } catch (err: any) {
      this.error = err?.message ?? String(err);
    }
  }

  private async removeItem(id: string): Promise<void> {
    if (!confirm(t(this.hass.language, "remove_confirm"))) return;
    await this.hass.callWS({ type: "homeai/presence/delete", exception_id: id });
    await this.load();
  }

  private form() {
    const lang = this.hass.language;
    const d = this.draft!;
    const set = (patch: Partial<Draft>) => (this.draft = { ...d, ...patch });
    const field = (label: string, content: unknown) => html`<label class="row" style="margin: 6px 0"><span style="min-width: 9em">${label}</span>${content}</label>`;
    return html`<div class="card">
      ${field(t(lang, "presence_kind"), html`<select @change=${(e: Event) => set({ kind: (e.target as HTMLSelectElement).value })}>
        ${KINDS.map((k) => html`<option value=${k} ?selected=${k === d.kind}>${t(lang, `presence_${k}`)}</option>`)}</select>`)}
      ${field(t(lang, "presence_person"), html`<select @change=${(e: Event) => set({ person: (e.target as HTMLSelectElement).value })}>
        <option value="" ?selected=${!d.person}>${t(lang, "presence_everyone")}</option>
        ${(this.world?.persons ?? []).map((p) => html`<option value=${p.id} ?selected=${p.id === d.person}>${p.name}</option>`)}</select>`)}
      ${field(t(lang, "presence_from"), html`<input type="date" .value=${d.start} @change=${(e: Event) => set({ start: (e.target as HTMLInputElement).value })} />`)}
      ${field(t(lang, "presence_to"), html`<input type="date" .value=${d.end} @change=${(e: Event) => set({ end: (e.target as HTMLInputElement).value })} />`)}
      ${field(t(lang, "presence_note"), html`<input class="grow" maxlength="300" .value=${d.note} @input=${(e: Event) => set({ note: (e.target as HTMLInputElement).value })} />`)}
      ${this.error ? html`<div class="muted" style="color: var(--error-color)">${this.error}</div>` : nothing}
      <div class="row" style="margin-top: 8px">
        <button class="primary" @click=${this.save}>${t(lang, "save")}</button>
        <button @click=${() => { this.draft = undefined; this.error = ""; }}>${t(lang, "cancel")}</button>
      </div>
    </div>`;
  }

  render() {
    const lang = this.hass.language;
    return html`
      <div class="row" style="margin-bottom: 12px">
        <span class="muted grow">${t(lang, "presence_hint")}</span>
        ${this.draft ? nothing : html`<button class="primary" @click=${() => (this.draft = { kind: "away", person: "", start: day(), end: day(1), note: "" })}>${t(lang, "presence_add")}</button>`}
      </div>
      ${this.draft ? this.form() : nothing}
      ${this.items.length
        ? html`<div class="card"><ul class="plain">${this.items.map(
            (i) => html`<li class="row"><span class="grow">${t(lang, `presence_${i.kind}`)} · ${this.personName(i.person)}<br />
              <span class="muted">${when(i.start, lang)} → ${when(i.end, lang)}${i.note ? ` · ${i.note}` : ""}</span></span>
              <button @click=${() => (this.draft = { id: i.id, kind: i.kind, person: i.person ?? "", start: localDay(i.start), end: localDay(i.end, true), note: i.note })}>${t(lang, "edit")}</button>
              <button @click=${() => this.removeItem(i.id)}>${t(lang, "remove")}</button></li>`,
          )}</ul></div>`
        : html`<div class="empty">${t(lang, "presence_none")}</div>`}`;
  }
}
