import { LitElement, html } from "lit";
import { property, state } from "lit/decorators.js";
import { element } from "../define";
import { t, when } from "../i18n";
import { shared } from "../styles";
import type { Approval, HomeAssistant } from "../types";

@element("homeai-approvals")
export class HomeAIApprovals extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;
  @state() private pending: Approval[] = [];
  @state() private recent: Approval[] = [];
  @state() private error = "";
  private unsub?: () => void;

  static styles = shared;

  async connectedCallback(): Promise<void> {
    super.connectedCallback();
    this.unsub = await this.hass.connection.subscribeMessage<{ pending: Approval[] }>(
      (msg) => (this.pending = msg.pending),
      { type: "homeai/approvals/subscribe" },
    );
    const list = await this.hass.callWS<{ recent: Approval[] }>({ type: "homeai/approvals/list" });
    this.recent = list.recent.filter((a) => a.status !== "pending");
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    this.unsub?.();
  }

  private async decide(verb: "approve" | "deny", a: Approval): Promise<void> {
    this.error = "";
    try {
      await this.hass.callWS({ type: `homeai/approvals/${verb}`, approval_id: a.id });
    } catch (err: any) {
      this.error = err?.message ?? String(err);
    }
  }

  render() {
    const lang = this.hass.language;
    return html`
      ${this.error ? html`<div class="card" style="color: var(--error-color)">${this.error}</div>` : ""}
      ${this.pending.length
        ? this.pending.map(
            (a) => html`<div class="card">
              <div class="row"><span class="sev sev-${Math.min(a.risk, 4)}">R${a.risk}</span><span class="title grow">${a.what}</span>
                <span class="muted">${t(lang, "expires")} ${when(a.expires, lang)}</span></div>
              <p class="muted">${a.reason}</p>
              <div class="row"><button class="primary" @click=${() => this.decide("approve", a)}>${t(lang, "approve")}</button>
                <button @click=${() => this.decide("deny", a)}>${t(lang, "deny")}</button></div>
            </div>`,
          )
        : html`<div class="empty">${t(lang, "no_approvals")}</div>`}
      ${this.recent.length
        ? html`<div class="card"><ul class="plain">${this.recent.slice(0, 15).map(
            (a) => html`<li class="row"><span class="grow">${a.what}</span><span class="muted">${a.status}${a.decided_by ? ` · ${a.decided_by}` : ""}</span></li>`,
          )}</ul></div>`
        : ""}
    `;
  }
}
