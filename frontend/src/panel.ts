import { LitElement, css, html } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import { t } from "./i18n";
import { shared } from "./styles";
import type { HomeAssistant } from "./types";
import "./views/situations";
import "./views/approvals";
import "./views/plan";
import "./views/journal";
import "./views/settings";
import "./views/ai";
import "./views/learning";

const TABS = ["situations", "approvals", "plan", "learning", "journal", "settings", "ai"] as const;
type Tab = (typeof TABS)[number];

@customElement("homeai-panel")
export class HomeAIPanel extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;
  @property({ type: Boolean }) narrow = false;
  @state() private tab: Tab = "situations";

  static styles = [
    shared,
    css`
      .toolbar { display: flex; align-items: center; height: var(--header-height, 56px); padding: 0 12px; gap: 8px;
        background: var(--app-header-background-color, var(--primary-color)); color: var(--app-header-text-color, #fff); }
      .toolbar h1 { font-size: 20px; font-weight: 400; margin: 0; flex: 1; }
      nav { display: flex; gap: 4px; padding: 8px 12px; overflow-x: auto; border-bottom: 1px solid var(--divider-color); }
      nav button { border: none; border-radius: 0; border-bottom: 2px solid transparent; color: var(--primary-text-color); }
      nav button.active { border-bottom-color: var(--primary-color); color: var(--primary-color); }
      main { padding: 16px; max-width: 960px; margin: 0 auto; }
    `,
  ];

  connectedCallback(): void {
    super.connectedCallback();
    const wanted = new URLSearchParams(location.search).get("tab") as Tab | null;
    if (wanted && TABS.includes(wanted)) this.tab = wanted;
  }

  private view() {
    switch (this.tab) {
      case "approvals": return html`<homeai-approvals .hass=${this.hass}></homeai-approvals>`;
      case "plan": return html`<homeai-plan .hass=${this.hass}></homeai-plan>`;
      case "journal": return html`<homeai-journal .hass=${this.hass}></homeai-journal>`;
      case "settings": return html`<homeai-settings .hass=${this.hass}></homeai-settings>`;
      case "ai": return html`<homeai-ai .hass=${this.hass}></homeai-ai>`;
      case "learning": return html`<homeai-learning .hass=${this.hass}></homeai-learning>`;
      default: return html`<homeai-situations .hass=${this.hass}></homeai-situations>`;
    }
  }

  render() {
    if (!this.hass) return html``;
    const lang = this.hass.language;
    return html`
      <div class="toolbar">
        <ha-menu-button .hass=${this.hass} .narrow=${this.narrow}></ha-menu-button>
        <h1>HomeAI</h1>
      </div>
      <nav>
        ${TABS.map((tab) => html`<button class=${tab === this.tab ? "active" : ""} @click=${() => (this.tab = tab)}>${t(lang, tab)}</button>`)}
      </nav>
      <main>${this.view()}</main>
    `;
  }
}
