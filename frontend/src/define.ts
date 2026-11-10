// Registers a custom element once. Home Assistant may load the bundle twice (as a module and, for browsers that
// get its legacy build, as a plain script); a second define must not throw and stop the rest of the bundle.
export function element(name: string) {
  return (cls: CustomElementConstructor): void => {
    if (!customElements.get(name)) customElements.define(name, cls);
  };
}
