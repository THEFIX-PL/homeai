import { LitElement, html, nothing } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import { t, when } from "./i18n";
import { shared } from "./styles";
import type { HomeAssistant } from "./types";

interface CardConfig { type: string; entity?: string; title?: string; min_severity?: number }
interface Item { id: string; title: string; severity: number; since: string; acknowledged: boolean; repairing: boolean; who: string | null }

// Lovelace card: open situations with quick reactions. Reads sensor.homeai_situations; no setup needed.
@customElement("homeai-situations-card")
export class HomeAISituationsCard extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;
  @state() private config: CardConfig = { type: "custom:homeai-situations-card" };

  static styles = shared;

  setConfig(config: CardConfig): void {
    this.config = { entity: "sensor.homeai_situations", min_severity: 1, ...config };
  }

  getCardSize(): number {
    return 3;
  }

  static getStubConfig(): CardConfig {
    return { type: "custom:homeai-situations-card" };
  }

  private act(service: string, id: string): void {
    this.hass.callService("homeai", service, { situation_id: id });
  }

  render() {
    if (!this.hass) return nothing;
    const lang = this.hass.language;
    const entity = this.hass.states[this.config.entity ?? "sensor.homeai_situations"];
    const items = ((entity?.attributes.situations ?? []) as Item[]).filter((s) => s.severity >= (this.config.min_severity ?? 1));
    return html`<div class="card">
      ${this.config.title ? html`<div class="title" style="margin-bottom: 8px">${this.config.title}</div>` : nothing}
      ${items.length
        ? html`<ul class="plain">${items.map(
            (s) => html`<li>
              <div class="row"><span class="sev sev-${s.severity}">${s.severity}</span><span class="grow">${s.title}</span>
                <span class="muted">${when(s.since, lang)}</span></div>
              ${s.repairing ? html`<div class="muted">${t(lang, "repairing")}</div>` : nothing}
              <div class="row" style="margin-top: 6px">
                <button @click=${() => this.act("acknowledge", s.id)} ?disabled=${s.acknowledged}>${t(lang, "ack")}</button>
                <button @click=${() => this.act("handle", s.id)}>${t(lang, "handle")}</button>
                <button @click=${() => this.act("snooze", s.id)}>${t(lang, "snooze")}</button>
              </div></li>`,
          )}</ul>`
        : html`<div class="muted">${t(lang, "nothing_open")}</div>`}
    </div>`;
  }
}

declare global {
  interface Window { customCards?: { type: string; name: string; description: string; preview?: boolean }[] }
}

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "homeai-situations-card")) {
  window.customCards.push({
    type: "homeai-situations-card",
    name: "HomeAI situations",
    description: "Open situations from HomeAI with quick reactions.",
    preview: true,
  });
}
