import { LitElement, html, nothing } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import { t } from "../i18n";
import { shared } from "../styles";
import type { HomeAssistant } from "../types";

interface AIStatus {
  enabled: boolean;
  tiers?: Record<string, { model: string; provider: string; priority: number; status: string | null }[]>;
  ledger?: { today: number; month: number; calls_today: number; limits: { period: string; spent: number; limit: number }[]; allowed: boolean };
  last_prompts?: Record<string, { ts: string; model: string; purpose: string; system: string; messages: unknown[]; answer: string; cost: number }>;
}

interface Prompt { mission: string; key: string; default: string; custom: string }

@customElement("homeai-ai")
export class HomeAIAI extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;
  @state() private status?: AIStatus;
  @state() private prompts: Prompt[] = [];
  @state() private message = "";

  static styles = shared;

  async connectedCallback(): Promise<void> {
    super.connectedCallback();
    if (!this.hass.user.is_admin) return;
    this.status = await this.hass.callWS<AIStatus>({ type: "homeai/ai/status" });
    await this.loadPrompts();
  }

  private async loadPrompts(): Promise<void> {
    this.prompts = (await this.hass.callWS<{ prompts: Prompt[] }>({ type: "homeai/ai/prompts" })).prompts;
  }

  private async savePrompt(p: Prompt, value: string): Promise<void> {
    try {
      await this.hass.callWS({ type: "homeai/settings/set", key: p.key, value });
      this.message = `${t(this.hass.language, `prompt_${p.mission}`)}: ${t(this.hass.language, "saved")}`;
    } catch (err: any) {
      this.message = err?.message ?? String(err);
    }
    await this.loadPrompts();
  }

  private async restorePrompt(p: Prompt): Promise<void> {
    await this.hass.callWS({ type: "homeai/settings/reset", key: p.key });
    this.message = `${t(this.hass.language, `prompt_${p.mission}`)}: ${t(this.hass.language, "prompt_restored")}`;
    await this.loadPrompts();
  }

  private promptCard(p: Prompt) {
    const lang = this.hass.language;
    let draft = p.custom || p.default;
    return html`<details class="card"><summary class="row"><span class="title grow">${t(lang, `prompt_${p.mission}`)}</span>
        <span class="muted">${p.custom ? t(lang, "prompt_custom") : t(lang, "prompt_default")}</span></summary>
      <p class="muted">${t(lang, "prompt_hint")}</p>
      <textarea style="min-height: 240px" .value=${draft} @input=${(e: Event) => (draft = (e.target as HTMLTextAreaElement).value)}></textarea>
      <div class="row" style="margin-top: 8px">
        <button class="primary" @click=${() => this.savePrompt(p, draft.trim() === p.default.trim() ? "" : draft)}>${t(lang, "save")}</button>
        ${p.custom ? html`<button @click=${() => this.restorePrompt(p)}>${t(lang, "prompt_restore")}</button>` : nothing}
      </div>
      ${p.custom ? html`<details><summary class="muted">${t(lang, "prompt_show_default")}</summary><textarea readonly style="min-height: 200px">${p.default}</textarea></details>` : nothing}
    </details>`;
  }

  render() {
    const lang = this.hass.language;
    if (!this.hass.user.is_admin) return html`<div class="empty">${t(lang, "admin_only")}</div>`;
    const s = this.status;
    if (!s) return nothing;
    const tiers = Object.entries(s.tiers ?? {});
    return html`
      <div class="card row">
        <div class="grow"><div class="muted">${t(lang, "cost_today")}</div><div class="title">$${(s.ledger?.today ?? 0).toFixed(3)}</div></div>
        <div class="grow"><div class="muted">${t(lang, "cost_month")}</div><div class="title">$${(s.ledger?.month ?? 0).toFixed(2)}</div></div>
        ${(s.ledger?.limits ?? []).map((l) => html`<div class="grow"><div class="muted">${l.period}</div><div>${l.spent.toFixed(2)} / ${l.limit}</div></div>`)}
      </div>
      <div class="card">
        <div class="title">${t(lang, "tiers")}</div>
        ${tiers.length
          ? html`<ul class="plain">${tiers.flatMap(([tier, list]) => list.map((c) => html`<li class="row"><b>${tier.toUpperCase()}</b>
              <span class="grow">${c.model} <span class="muted">(${c.provider}, ${c.priority})</span></span><span class="muted">${c.status ?? "—"}</span></li>`))}</ul>`
          : html`<p class="muted">${t(lang, "no_tiers")}</p>`}
      </div>
      <div class="title" style="margin: 16px 0 8px">${t(lang, "prompts")}</div>
      ${this.message ? html`<div class="card muted">${this.message}</div>` : nothing}
      ${this.prompts.map((p) => this.promptCard(p))}
      ${Object.entries(s.last_prompts ?? {}).map(
        ([tier, p]) => html`<div class="card"><div class="title">${t(lang, "last_prompt")} · ${tier.toUpperCase()} · ${p.model} · ${p.purpose} · $${p.cost.toFixed(4)}</div>
          <details><summary class="muted">${p.ts}</summary><textarea readonly>${JSON.stringify(p.messages, null, 2)}</textarea><textarea readonly>${p.answer}</textarea></details></div>`,
      )}`;
  }
}
