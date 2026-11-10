import { LitElement, html } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import { t, when } from "../i18n";
import { shared } from "../styles";
import type { HomeAssistant } from "../types";

interface Occurrence { at: string; entry_id: string; title: string }
interface Entry { id: string; title: string; when: Record<string, unknown>; author_name: string; last_result: string | null }

@customElement("homeai-plan")
export class HomeAIPlan extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;
  @state() private occurrences: Occurrence[] = [];
  @state() private entries: Entry[] = [];

  static styles = shared;

  connectedCallback(): void {
    super.connectedCallback();
    this.load();
  }

  private async load(): Promise<void> {
    const res = await this.hass.callWS<{ entries: Entry[]; occurrences: Occurrence[] }>({ type: "homeai/plan/list", days: 14 });
    this.entries = res.entries;
    this.occurrences = res.occurrences;
  }

  private async removeEntry(id: string): Promise<void> {
    await this.hass.callWS({ type: "homeai/plan/delete", entry_id: id });
    await this.load();
  }

  render() {
    const lang = this.hass.language;
    if (!this.entries.length) return html`<div class="empty">${t(lang, "no_plan")}</div>`;
    return html`
      <div class="card"><ul class="plain">
        ${this.occurrences.slice(0, 40).map((o) => html`<li class="row"><span class="muted">${when(o.at, lang)}</span><span class="grow">${o.title}</span></li>`)}
      </ul></div>
      <div class="card"><ul class="plain">
        ${this.entries.map(
          (e) => html`<li class="row"><span class="grow">${e.title}<br /><span class="muted">${e.author_name} · ${JSON.stringify(e.when)}</span></span>
            <button @click=${() => this.removeEntry(e.id)}>${t(lang, "remove")}</button></li>`,
        )}
      </ul></div>`;
  }
}
