import { LitElement, css, html, nothing } from "lit";
import { property, query, state } from "lit/decorators.js";
import { element } from "../define";
import { t } from "../i18n";
import { shared } from "../styles";
import type { ChatMessage, HomeAssistant } from "../types";

const STORAGE_KEY = "homeai-chat-conversation";

function remembered(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function remember(key: string, value: string | null): void {
  try {
    if (value) sessionStorage.setItem(key, value);
    else sessionStorage.removeItem(key);
  } catch {
    /* storage unavailable: the thread lasts until the page closes */
  }
}

// A conversation with HomeAI in the viewer's own account. Used by the panel's Chat tab and the chat card.
@element("homeai-chat")
export class HomeAIChat extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;
  @property({ attribute: "storage-key" }) storageKey = STORAGE_KEY;
  @property({ type: Boolean }) compact = false;
  @state() private messages: ChatMessage[] = [];
  @state() private busy = false;
  @state() private error = "";
  @query("textarea") private box?: HTMLTextAreaElement;
  @query(".log") private log?: HTMLElement;
  private conversation: string | null = null;

  static styles = [
    shared,
    css`
      .log { display: flex; flex-direction: column; gap: 8px; max-height: 60vh; overflow-y: auto; padding: 4px 0 12px; }
      :host([compact]) .log { max-height: 320px; }
      .msg { max-width: 85%; padding: 8px 12px; border-radius: 14px; white-space: pre-wrap; overflow-wrap: anywhere; }
      .user { align-self: flex-end; background: var(--primary-color); color: var(--text-primary-color, #fff); }
      .assistant { align-self: flex-start; background: var(--secondary-background-color, #f1f1f1); }
      textarea { min-height: 44px; font-family: inherit; font-size: 1em; }
    `,
  ];

  connectedCallback(): void {
    super.connectedCallback();
    this.conversation = remembered(this.storageKey);
    if (this.conversation) this.loadHistory();
  }

  private async loadHistory(): Promise<void> {
    const res = await this.hass.callWS<{ messages: ChatMessage[] }>({ type: "homeai/chat/history", conversation_id: this.conversation });
    this.messages = res.messages;
    this.scrollDown();
  }

  private scrollDown(): void {
    this.updateComplete.then(() => this.log?.scrollTo({ top: this.log.scrollHeight }));
  }

  private async send(): Promise<void> {
    const text = this.box?.value.trim();
    if (!text || this.busy) return;
    this.box!.value = "";
    this.messages = [...this.messages, { role: "user", text }];
    this.busy = true;
    this.error = "";
    this.scrollDown();
    try {
      const res = await this.hass.callWS<{ reply: string; conversation_id: string }>({
        type: "homeai/chat/send",
        text,
        ...(this.conversation ? { conversation_id: this.conversation } : {}),
      });
      this.conversation = res.conversation_id;
      remember(this.storageKey, this.conversation);
      this.messages = [...this.messages, { role: "assistant", text: res.reply }];
    } catch (err: any) {
      this.error = err?.message ?? String(err);
    } finally {
      this.busy = false;
      this.scrollDown();
    }
  }

  private restart(): void {
    this.conversation = null;
    remember(this.storageKey, null);
    this.messages = [];
  }

  private keydown(e: KeyboardEvent): void {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      this.send();
    }
  }

  render() {
    const lang = this.hass.language;
    return html`
      <div class="log" aria-live="polite">
        ${this.messages.length ? nothing : html`<div class="muted">${t(lang, "chat_hint")}</div>`}
        ${this.messages.map((m) => html`<div class="msg ${m.role}">${m.text}</div>`)}
        ${this.busy ? html`<div class="msg assistant muted">…</div>` : nothing}
      </div>
      ${this.error ? html`<div class="muted" style="color: var(--error-color)">${this.error}</div>` : nothing}
      <div class="row">
        <textarea class="grow" placeholder=${t(lang, "chat_placeholder")} @keydown=${this.keydown} ?disabled=${this.busy}></textarea>
      </div>
      <div class="row" style="margin-top: 8px">
        <button class="primary" @click=${this.send} ?disabled=${this.busy}>${t(lang, "send")}</button>
        <span class="grow"></span>
        ${this.messages.length ? html`<button @click=${this.restart}>${t(lang, "chat_new")}</button>` : nothing}
      </div>`;
  }
}
