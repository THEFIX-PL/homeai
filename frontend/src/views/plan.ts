import { LitElement, html, nothing } from "lit";
import { property, state } from "lit/decorators.js";
import { element } from "../define";
import { t, when } from "../i18n";
import { shared } from "../styles";
import type { HomeAssistant } from "../types";

interface When { kind: string; time?: string; date?: string; days?: number[]; event?: string; offset?: number }
interface Occurrence { at: string; entry_id: string; title: string; external?: boolean; source?: string | null }
interface Watch { id: string; what: string; message: string; expires: string; person: string }
interface Entry {
  id: string;
  title: string;
  when: When;
  enabled: boolean;
  skip_when_away: boolean;
  author_name: string;
  last_result: string | null;
  reminder?: string;
  to?: string;
  action?: { service: string; entity_ids: string[]; data: Record<string, unknown> };
}
interface Draft {
  id?: string;
  type: "action" | "reminder";
  title: string;
  service: string;
  entities: string;
  data: string;
  reminder: string;
  to: string;
  when: When;
  enabled: boolean;
  skip_when_away: boolean;
}

const KINDS = ["once", "daily", "weekly", "sun"];
const EVENTS = ["sunrise", "sunset", "dawn", "dusk", "solar_noon"];
const TO = ["home_or_all", "home", "all", "admins"];
const SERVICES = ["light.turn_on", "light.turn_off", "switch.turn_on", "switch.turn_off", "cover.open_cover", "cover.close_cover",
  "climate.set_temperature", "scene.turn_on", "script.turn_on", "media_player.media_stop", "fan.turn_off", "input_boolean.turn_on",
  "input_boolean.turn_off"];

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function blank(): Draft {
  return { type: "action", title: "", service: "light.turn_off", entities: "", data: "", reminder: "", to: "home_or_all",
    when: { kind: "daily", time: "08:00" }, enabled: true, skip_when_away: false };
}

function fromEntry(e: Entry): Draft {
  return {
    id: e.id, type: e.reminder ? "reminder" : "action", title: e.title, service: e.action?.service ?? "",
    entities: (e.action?.entity_ids ?? []).join(", "), data: e.action && Object.keys(e.action.data).length ? JSON.stringify(e.action.data) : "",
    reminder: e.reminder ?? "", to: e.to ?? "home_or_all", when: { ...e.when }, enabled: e.enabled, skip_when_away: e.skip_when_away,
  };
}

export function describeWhen(w: When, lang: string): string {
  const names = Array.from({ length: 7 }, (_, i) => new Date(2024, 0, 1 + i).toLocaleDateString(lang, { weekday: "short" }));
  const days = w.days?.length ? w.days.map((d) => names[d]).join(", ") : "";
  switch (w.kind) {
    case "once": return `${w.date} ${w.time}`;
    case "daily": return `${t(lang, "plan_daily")} ${w.time}`;
    case "weekly": return `${days} ${w.time}`;
    case "sun": {
      const off = w.offset ? ` ${w.offset > 0 ? "+" : ""}${w.offset} min` : "";
      return `${t(lang, `plan_${w.event}`)}${off}${days ? ` · ${days}` : ""}`;
    }
    default: return JSON.stringify(w);
  }
}

// The home's plan: what happens next, every entry, and a form to add or change one.
@element("homeai-plan")
export class HomeAIPlan extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;
  @state() private occurrences: Occurrence[] = [];
  @state() private entries: Entry[] = [];
  @state() private watches: Watch[] = [];
  @state() private draft?: Draft;
  @state() private error = "";
  @state() private all = false;

  static styles = shared;

  connectedCallback(): void {
    super.connectedCallback();
    this.load();
  }

  private async load(): Promise<void> {
    const res = await this.hass.callWS<{ entries: Entry[]; occurrences: Occurrence[] }>({ type: "homeai/plan/list", days: 14 });
    this.entries = res.entries;
    this.occurrences = res.occurrences;
    try {
      this.watches = (await this.hass.callWS<{ items: Watch[] }>({ type: "homeai/watches/list" })).items;
    } catch {
      this.watches = [];
    }
  }

  private async removeWatch(id: string): Promise<void> {
    await this.hass.callWS({ type: "homeai/watches/delete", watch_id: id });
    await this.load();
  }

  private async removeEntry(id: string): Promise<void> {
    if (!confirm(t(this.hass.language, "remove_confirm"))) return;
    await this.hass.callWS({ type: "homeai/plan/delete", entry_id: id });
    await this.load();
  }

  private async skip(o: Occurrence): Promise<void> {
    const d = new Date(o.at);
    const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    await this.hass.callService("homeai", "plan_skip", { entry_id: o.entry_id, date });
    await this.load();
  }

  private set(patch: Partial<Draft>): void {
    this.draft = { ...this.draft!, ...patch };
  }

  private setWhen(patch: Partial<When>): void {
    const w = { ...this.draft!.when, ...patch };
    if (patch.kind) {
      if (w.kind === "once" && !w.date) w.date = today();
      if ((w.kind === "weekly") && !w.days?.length) w.days = [0, 1, 2, 3, 4];
      if (w.kind === "sun" && !w.event) w.event = "sunset";
      if (w.kind !== "sun" && !w.time) w.time = "08:00";
    }
    this.set({ when: w });
  }

  private toggleDay(day: number): void {
    const days = new Set(this.draft!.when.days ?? []);
    days.has(day) ? days.delete(day) : days.add(day);
    this.setWhen({ days: [...days].sort() });
  }

  private async save(): Promise<void> {
    const d = this.draft!;
    const w: When = { kind: d.when.kind };
    if (d.when.kind !== "sun") w.time = d.when.time;
    if (d.when.kind === "once") w.date = d.when.date;
    if (d.when.kind === "weekly" || (d.when.kind === "sun" && d.when.days?.length)) w.days = d.when.days;
    if (d.when.kind === "sun") {
      w.event = d.when.event;
      w.offset = Number(d.when.offset ?? 0);
    }
    const entry: Record<string, unknown> = { title: d.title, when: w, enabled: d.enabled, skip_when_away: d.skip_when_away };
    if (d.type === "reminder") {
      entry.reminder = d.reminder;
      entry.to = d.to;
    } else {
      let data = {};
      try {
        data = d.data.trim() ? JSON.parse(d.data) : {};
      } catch (err) {
        this.error = `JSON: ${err}`;
        return;
      }
      entry.action = { service: d.service.trim(), entity_ids: d.entities.split(/[\s,]+/).filter(Boolean), data };
    }
    try {
      await this.hass.callWS({ type: "homeai/plan/save", entry, ...(d.id ? { entry_id: d.id } : {}) });
      this.draft = undefined;
      this.error = "";
      await this.load();
    } catch (err: any) {
      this.error = `${t(this.hass.language, "plan_error")}: ${err?.message ?? err}`;
    }
  }

  private form() {
    const lang = this.hass.language;
    const d = this.draft!;
    const w = d.when;
    const names = Array.from({ length: 7 }, (_, i) => new Date(2024, 0, 1 + i).toLocaleDateString(lang, { weekday: "short" }));
    const field = (label: string, content: unknown) => html`<label class="row" style="margin: 6px 0"><span style="min-width: 9em">${label}</span>${content}</label>`;
    return html`<div class="card">
      ${field(t(lang, "plan_type"), html`<select @change=${(e: Event) => this.set({ type: (e.target as HTMLSelectElement).value as Draft["type"] })}>
        <option value="action" ?selected=${d.type === "action"}>${t(lang, "plan_action")}</option>
        <option value="reminder" ?selected=${d.type === "reminder"}>${t(lang, "plan_reminder")}</option></select>`)}
      ${field(t(lang, "rule_name"), html`<input class="grow" .value=${d.title} @input=${(e: Event) => this.set({ title: (e.target as HTMLInputElement).value })} />`)}
      ${d.type === "reminder"
        ? html`${field(t(lang, "plan_reminder_text"), html`<input class="grow" .value=${d.reminder} @input=${(e: Event) => this.set({ reminder: (e.target as HTMLInputElement).value })} />`)}
          ${field(t(lang, "plan_to"), html`<select @change=${(e: Event) => this.set({ to: (e.target as HTMLSelectElement).value })}>
            ${TO.map((x) => html`<option value=${x} ?selected=${x === d.to}>${t(lang, `plan_to_${x}`)}</option>`)}</select>`)}`
        : html`${field(t(lang, "plan_service"), html`<input class="grow" list="homeai-services" .value=${d.service} @input=${(e: Event) => this.set({ service: (e.target as HTMLInputElement).value })} />
            <datalist id="homeai-services">${SERVICES.map((s) => html`<option value=${s}></option>`)}</datalist>`)}
          ${field(t(lang, "rule_entities"), html`<input class="grow" list="homeai-entities" placeholder="light.kitchen, light.hall" .value=${d.entities} @input=${(e: Event) => this.set({ entities: (e.target as HTMLInputElement).value })} />
            <datalist id="homeai-entities">${Object.keys(this.hass.states).map((id) => html`<option value=${id}></option>`)}</datalist>`)}
          ${field(t(lang, "plan_data"), html`<input class="grow" placeholder='{"brightness_pct": 30}' .value=${d.data} @input=${(e: Event) => this.set({ data: (e.target as HTMLInputElement).value })} />`)}`}
      ${field(t(lang, "plan_when"), html`<select @change=${(e: Event) => this.setWhen({ kind: (e.target as HTMLSelectElement).value })}>
        ${KINDS.map((k) => html`<option value=${k} ?selected=${k === w.kind}>${t(lang, `plan_${k}`)}</option>`)}</select>
        ${w.kind === "once" ? html`<input type="date" .value=${w.date ?? ""} @change=${(e: Event) => this.setWhen({ date: (e.target as HTMLInputElement).value })} />` : nothing}
        ${w.kind === "sun"
          ? html`<select @change=${(e: Event) => this.setWhen({ event: (e.target as HTMLSelectElement).value })}>
              ${EVENTS.map((x) => html`<option value=${x} ?selected=${x === w.event}>${t(lang, `plan_${x}`)}</option>`)}</select>
              <input type="number" style="width: 6em" min="-720" max="720" .value=${String(w.offset ?? 0)} @change=${(e: Event) => this.setWhen({ offset: parseInt((e.target as HTMLInputElement).value, 10) || 0 })} /> min`
          : html`<input type="time" .value=${w.time ?? ""} @change=${(e: Event) => this.setWhen({ time: (e.target as HTMLInputElement).value })} />`}`)}
      ${w.kind === "weekly" || w.kind === "sun"
        ? html`<div class="row">${names.map((n, i) => html`<label class="row"><input type="checkbox" .checked=${(w.days ?? []).includes(i)} @change=${() => this.toggleDay(i)} />${n}</label>`)}</div>`
        : nothing}
      <label class="row" style="margin: 6px 0"><input type="checkbox" .checked=${d.skip_when_away} @change=${(e: Event) => this.set({ skip_when_away: (e.target as HTMLInputElement).checked })} />${t(lang, "plan_skip_away")}</label>
      <label class="row" style="margin: 6px 0"><input type="checkbox" .checked=${d.enabled} @change=${(e: Event) => this.set({ enabled: (e.target as HTMLInputElement).checked })} />${t(lang, "rule_enabled")}</label>
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
        <span class="grow"></span>
        ${this.draft ? nothing : html`<button class="primary" @click=${() => (this.draft = blank())}>${t(lang, "plan_add")}</button>`}
      </div>
      ${this.draft ? this.form() : nothing}
      ${this.entries.length ? html`
        <div class="card"><div class="title">${t(lang, "plan_next")}</div><ul class="plain">
          ${this.occurrences.slice(0, this.all ? 200 : 12).map((o) => html`<li class="row"><span class="muted">${when(o.at, lang)}</span>
            <span class="grow">${o.title}${o.external ? html` <span class="muted">· ${this.hass.states[o.source ?? ""]?.attributes.friendly_name ?? o.source}</span>` : nothing}</span>
            ${o.external ? nothing : html`<button title=${t(lang, "plan_skip")} @click=${() => this.skip(o)}>${t(lang, "plan_skip")}</button>`}</li>`)}
        </ul>
        ${this.occurrences.length > 12 ? html`<button style="margin-top: 8px" @click=${() => (this.all = !this.all)}>${this.all ? t(lang, "show_less") : `${t(lang, "show_all")} (${this.occurrences.length})`}</button>` : nothing}</div>
        <div class="card"><div class="title">${t(lang, "plan_entries")}</div><ul class="plain">
          ${this.entries.map(
            (e) => html`<li class="row"><span class="grow">${e.enabled ? "" : html`<span class="muted">(${t(lang, "rule_off")}) </span>`}${e.title}<br />
              <span class="muted">${describeWhen(e.when, lang)} · ${e.author_name}${e.last_result ? ` · ${e.last_result}` : ""}</span></span>
              <button @click=${() => (this.draft = fromEntry(e))}>${t(lang, "edit")}</button>
              <button @click=${() => this.removeEntry(e.id)}>${t(lang, "remove")}</button></li>`,
          )}
        </ul></div>` : html`<div class="empty">${t(lang, "no_plan")}</div>`}
      ${this.watches.length ? html`<div class="card"><div class="title">${t(lang, "watching")}</div><ul class="plain">
        ${this.watches.map((w) => html`<li class="row"><span class="grow">${w.what}${w.message ? html`<br /><span class="muted">${w.message}</span>` : nothing}<br />
          <span class="muted">${t(lang, "until")} ${when(w.expires, lang)}</span></span>
          <button @click=${() => this.removeWatch(w.id)}>${t(lang, "remove")}</button></li>`)}
      </ul></div>` : nothing}`;
  }
}
