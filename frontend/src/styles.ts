import { css } from "lit";

export const shared = css`
  :host { display: block; color: var(--primary-text-color); font-family: var(--paper-font-body1_-_font-family, inherit); }
  .card { background: var(--card-background-color, #fff); border-radius: var(--ha-card-border-radius, 12px);
    box-shadow: var(--ha-card-box-shadow, none); border: 1px solid var(--divider-color, #e0e0e0); padding: 16px; margin-bottom: 12px; }
  .row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .grow { flex: 1 1 auto; min-width: 0; }
  .muted { color: var(--secondary-text-color); font-size: 0.9em; }
  .title { font-weight: 500; font-size: 1.05em; }
  button { font: inherit; border: 1px solid var(--divider-color, #ccc); background: transparent; color: var(--primary-color);
    border-radius: 18px; padding: 6px 14px; cursor: pointer; }
  button.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  button:disabled { opacity: 0.5; cursor: default; }
  .sev { display: inline-block; min-width: 1.6em; text-align: center; border-radius: 10px; padding: 0 6px; font-size: 0.85em;
    color: #fff; background: var(--secondary-text-color); }
  .sev-4 { background: var(--error-color, #db4437); } .sev-3 { background: var(--warning-color, #ffa600); }
  .sev-2 { background: var(--info-color, #039be5); } .sev-1 { background: var(--success-color, #43a047); }
  input, select, textarea { font: inherit; color: var(--primary-text-color); background: var(--input-fill-color, transparent);
    border: 1px solid var(--divider-color, #ccc); border-radius: 6px; padding: 6px 8px; box-sizing: border-box; }
  textarea { width: 100%; min-height: 80px; font-family: var(--code-font-family, monospace); font-size: 0.9em; }
  .empty { padding: 32px; text-align: center; color: var(--secondary-text-color); }
  ul.plain { list-style: none; padding: 0; margin: 0; } ul.plain li { padding: 6px 0; border-bottom: 1px solid var(--divider-color, #eee); }
`;
