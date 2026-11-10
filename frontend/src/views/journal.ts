import { LitElement, html } from "lit";
import { property, state } from "lit/decorators.js";
import { element } from "../define";
import { t, when } from "../i18n";
import { shared } from "../styles";
import type { HomeAssistant, JournalEntry } from "../types";

@element("homeai-journal")
export class HomeAIJournal extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;
  @state() private entries: JournalEntry[] = [];

  static styles = shared;

  async connectedCallback(): Promise<void> {
    super.connectedCallback();
    const res = await this.hass.callWS<{ entries: JournalEntry[] }>({ type: "homeai/journal/recent", limit: 200 });
    this.entries = res.entries;
  }

  render() {
    const lang = this.hass.language;
    return html`<div class="card"><ul class="plain">
      ${this.entries.map(
        (e) => html`<li class="row"><span class="muted" style="min-width: 9em">${when(e.ts, lang)}</span>
          <span class="muted" style="min-width: 7em">${t(lang, `kind_${e.kind}`).replace(/^kind_/, "")}</span><span class="grow">${e.text}</span></li>`,
      )}
    </ul></div>`;
  }
}
