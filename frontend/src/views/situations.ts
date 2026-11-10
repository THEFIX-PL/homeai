import { LitElement, html, nothing } from "lit";
import { property, state } from "lit/decorators.js";
import { element } from "../define";
import { t, when } from "../i18n";
import { shared } from "../styles";
import type { HomeAssistant, Situation } from "../types";

@element("homeai-situations")
export class HomeAISituations extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;
  @state() private open: Situation[] = [];
  @state() private resolved: Situation[] = [];
  private unsub?: () => void;

  static styles = shared;

  connectedCallback(): void {
    super.connectedCallback();
    this.subscribe();
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    this.unsub?.();
    this.unsub = undefined;
  }

  private async subscribe(): Promise<void> {
    if (!this.hass || this.unsub) return;
    this.unsub = await this.hass.connection.subscribeMessage<{ type: string; situations?: Situation[] }>(
      (msg) => {
        if (msg.type === "situations" && msg.situations) this.open = msg.situations;
      },
      { type: "homeai/situations/subscribe", language: this.hass.language },
    );
    const list = await this.hass.callWS<{ resolved: Situation[] }>({ type: "homeai/situations/list", resolved: 10 });
    this.resolved = list.resolved;
  }

  private async act(verb: string, s: Situation): Promise<void> {
    await this.hass.callWS({ type: `homeai/situations/${verb}`, situation_id: s.id });
  }

  private renderSituation(s: Situation) {
    const lang = this.hass.language;
    const a = s.assessment || {};
    const repairing = ["waiting", "trying", "verifying"].includes(s.repair?.status);
    return html`<div class="card">
      <div class="row">
        <span class="sev sev-${s.severity}" title=${t(lang, "severity")}>${s.severity}</span>
        <span class="title grow">${s.title}</span>
        <span class="muted">${t(lang, "since")} ${when(s.opened_at || s.first_seen, lang)}</span>
      </div>
      ${s.description ? html`<p>${s.description}</p>` : nothing}
      ${a.reason ? html`<p class="muted">${t(lang, "reason")}: ${a.reason}</p>` : nothing}
      ${a.steps?.length ? html`<ol>${a.steps.map((x: string) => html`<li>${x}</li>`)}</ol>` : nothing}
      ${repairing ? html`<p class="muted">${t(lang, "repairing")} (${s.repair.playbook})</p>` : nothing}
      ${s.acked_by ? html`<p class="muted">✓ ${s.acked_by}</p>` : nothing}
      <div class="row">
        <button @click=${() => this.act("ack", s)} ?disabled=${!!s.acked_by}>${t(lang, "ack")}</button>
        <button @click=${() => this.act("handle", s)}>${t(lang, "handle")}</button>
        <button @click=${() => this.act("snooze", s)}>${t(lang, "snooze")}</button>
        <button @click=${() => this.act("dismiss", s)}>${t(lang, "dismiss")}</button>
      </div>
    </div>`;
  }

  render() {
    const lang = this.hass.language;
    return html`
      ${this.open.length ? this.open.map((s) => this.renderSituation(s)) : html`<div class="empty">${t(lang, "nothing_open")}</div>`}
      ${this.resolved.length
        ? html`<h3>${t(lang, "resolved")}</h3>
            <div class="card"><ul class="plain">
              ${this.resolved.map((s) => html`<li class="row"><span class="grow">${s.title}</span><span class="muted">${when(s.opened_at || s.first_seen, lang)}</span></li>`)}
            </ul></div>`
        : nothing}
    `;
  }
}
