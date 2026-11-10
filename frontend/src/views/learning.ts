import { LitElement, html, nothing } from "lit";
import { property, state } from "lit/decorators.js";
import { element } from "../define";
import { t, when } from "../i18n";
import { shared } from "../styles";
import type { HomeAssistant } from "../types";

interface Proposal { id: string; title: string; days_seen: number; days_possible: number }
interface Fact { id: string; text: string; scope: string; source: string; approved: boolean; created: string }
interface Review { ts: string; text: string }

@element("homeai-learning")
export class HomeAILearning extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;
  @state() private proposals: Proposal[] = [];
  @state() private facts: Fact[] = [];
  @state() private reviews: Review[] = [];
  @state() private draft = "";

  static styles = shared;

  connectedCallback(): void {
    super.connectedCallback();
    this.load();
  }

  private async load(): Promise<void> {
    const res = await this.hass.callWS<{ proposals: Proposal[]; facts: Fact[]; reviews: Review[] }>({ type: "homeai/learning/status" });
    this.proposals = res.proposals;
    this.facts = res.facts;
    this.reviews = res.reviews;
  }

  private async call(type: string, data: Record<string, unknown>): Promise<void> {
    await this.hass.callWS({ type, ...data });
    await this.load();
  }

  private async remember(): Promise<void> {
    if (!this.draft.trim()) return;
    await this.call("homeai/memory/add", { text: this.draft });
    this.draft = "";
  }

  render() {
    const lang = this.hass.language;
    return html`
      <h3>${t(lang, "proposals")}</h3>
      ${this.proposals.length
        ? this.proposals.map(
            (p) => html`<div class="card row"><span class="grow">${p.title}<br /><span class="muted">${p.days_seen}/${p.days_possible}</span></span>
              <button class="primary" @click=${() => this.call("homeai/learning/approve", { proposal_id: p.id })}>${t(lang, "approve")}</button>
              <button @click=${() => this.call("homeai/learning/reject", { proposal_id: p.id })}>${t(lang, "deny")}</button></div>`,
          )
        : html`<div class="empty">${t(lang, "no_proposals")}</div>`}
      <h3>${t(lang, "memory")}</h3>
      <div class="card">
        <div class="row"><input class="grow" .value=${this.draft} placeholder=${t(lang, "remember_hint")}
          @input=${(e: Event) => (this.draft = (e.target as HTMLInputElement).value)} @keydown=${(e: KeyboardEvent) => e.key === "Enter" && this.remember()} />
          <button @click=${this.remember}>${t(lang, "remember")}</button></div>
        <ul class="plain">${this.facts.map(
          (f) => html`<li class="row"><span class="grow">${f.text} <span class="muted">${f.scope === "home" ? t(lang, "memory_home") : this.hass.states[f.scope.replace(/^person:/, "")]?.attributes.friendly_name ?? f.scope} · ${t(lang, `memory_from_${f.source}`)}</span></span>
            ${f.approved ? nothing : html`<button @click=${() => this.call("homeai/memory/approve", { fact_id: f.id })}>${t(lang, "approve")}</button>`}
            <button @click=${() => this.call("homeai/memory/remove", { fact_id: f.id })}>${t(lang, "remove")}</button></li>`,
        )}</ul>
      </div>
      ${this.reviews.length
        ? html`<h3>${t(lang, "review")}</h3><div class="card"><div class="muted">${when(this.reviews[0].ts, lang)}</div>
            <p style="white-space: pre-line">${this.reviews[0].text}</p></div>`
        : nothing}
    `;
  }
}
