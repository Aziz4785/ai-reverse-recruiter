from playwright.sync_api import sync_playwright

def auto_scroll(page, max_passes: int = 3):
    """Scrolls to the bottom a few times so lazy content loads."""
    for _ in range(max_passes):
        prev_height = page.evaluate("document.body ? document.body.scrollHeight : 0")
        # Smooth-scroll to bottom
        page.evaluate("""
        () => new Promise(resolve => {
          const distance = Math.max(400, Math.floor(window.innerHeight * 0.9));
          const timer = setInterval(() => {
            const { scrollTop, scrollHeight, clientHeight } = document.documentElement;
            window.scrollBy(0, distance);
            if (scrollTop + clientHeight >= scrollHeight - 2) {
              clearInterval(timer);
              resolve();
            }
          }, 50);
        })
        """)
        page.wait_for_timeout(250)
        new_height = page.evaluate("document.body ? document.body.scrollHeight : 0")
        if new_height == prev_height:
            break

_JS_GET_TEXT = """
() => {
  const chunks = [];

  // 1) Main rendered text (closest to what Ctrl+F sees)
  if (document.body && 'innerText' in document.body) {
    chunks.push(document.body.innerText);
  }

  // Helper: "visible enough" check
  const isVisible = (el) => {
    const style = getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') return false;
    // getClientRects covers many edge cases (positioned/fixed elements)
    return el.getClientRects().length > 0;
  };

  // 2) Add visible placeholders / titles / alt / input values
  try {
    const extras = document.querySelectorAll('input, textarea, img, [title]');
    for (const el of extras) {
      if (!(el instanceof HTMLElement)) continue;
      if (!isVisible(el)) continue;

      const t = [];
      // placeholders (visually shown)
      if ('placeholder' in el && el.placeholder) t.push(el.placeholder);
      // entered values (often visible)
      if ('value' in el && typeof el.value === 'string' && el.value) t.push(el.value);
      // tooltips that some sites render as visible labels too
      if (el.hasAttribute('title')) t.push(el.getAttribute('title') || '');
      // image alts (sometimes shown as captions/thumbnails)
      if (el.tagName === 'IMG' && el.hasAttribute('alt')) t.push(el.getAttribute('alt') || '');
      const s = t.filter(Boolean).join('\\n');
      if (s) chunks.push(s);
    }
  } catch {}

  // 3) Text inside OPEN shadow roots
  try {
    const walker = document.createTreeWalker(document, NodeFilter.SHOW_ELEMENT);
    let node;
    while ((node = walker.nextNode())) {
      const anyNode = node;
      if (anyNode.shadowRoot) {
        // Grab innerText of visible elements inside the shadow root
        for (const el of anyNode.shadowRoot.querySelectorAll('*')) {
          if (el instanceof HTMLElement && isVisible(el)) {
            const t = el.innerText;
            if (t && t.trim()) chunks.push(t);
          }
        }
      }
    }
  } catch {}

  // Normalize whitespace a bit
  const text = chunks.join('\\n').replace(/[\\t\\r]+/g, ' ').replace(/[ \\f\\v]+/g, ' ').replace(/\\n{2,}/g, '\\n');
  return text;
}
"""

def extract_all_visible_text(page, include_iframes: bool = True) -> str:
    """Return a single string approximating what the browser's find-in-page (Ctrl+F) can see."""
    base_text = page.evaluate(_JS_GET_TEXT) or ""
    parts = [base_text]

    if include_iframes:
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                t = frame.evaluate(_JS_GET_TEXT) or ""
                if t.strip():
                    parts.append(t)
            except Exception:
                # Cross-origin and about:blank frames may fail; just skip
                pass

    # Final clean-up: de-dup blank lines and trim
    out = "\n".join(
        line.strip()
        for line in "\n".join(parts).splitlines()
        if line.strip()
    )
    return out

# Example usage:
def run(url: str, headless: bool = True) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        # Optional: wait for network to calm down, then scroll to pull in lazy content
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        auto_scroll(page)

        text = extract_all_visible_text(page, include_iframes=True)

        browser.close()
        return text
