/** Yield so the browser can paint before heavy reactive/DOM work. */
export function yieldMainThread(): Promise<void> {
  return new Promise((resolve) => {
    requestAnimationFrame(() => resolve());
  });
}
