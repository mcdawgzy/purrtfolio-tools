// Research calls to action: email signup + "Request a test".
// Renders into every <div data-research-cta>. Each half stays hidden until its
// setting below is filled in, so the pages never show a dead form or link.
const BUTTONDOWN_USER = "";   // Buttondown username, e.g. "purrtfolio"
const REQUEST_FORM_URL = "";  // Tally form link, e.g. "https://tally.so/r/xxxxxx"

function signup() {
  if (!BUTTONDOWN_USER) return "";
  const action = `https://buttondown.com/api/emails/embed-subscribe/${encodeURIComponent(BUTTONDOWN_USER)}`;
  return `
    <div class="cta-part">
      <h3>Get the next study by email</h3>
      <p>One email per study: the claim, what we measured, and the verdict. No signals, no spam.</p>
      <form class="cta-form" action="${action}" method="post" target="_blank">
        <label class="sr-only" for="cta-email">Email address</label>
        <input id="cta-email" type="email" name="email" placeholder="you@example.com" autocomplete="email" required>
        <input type="hidden" name="tag" value="research">
        <button class="btn-primary" type="submit">Subscribe</button>
      </form>
    </div>`;
}

function request() {
  if (!REQUEST_FORM_URL) return "";
  return `
    <div class="cta-part">
      <h3>Want a strategy tested?</h3>
      <p>Send us the rules. A <b>public</b> test is published here with the source anonymised; a <b>private</b> test goes to you alone. Same method either way: tick data, real costs, a decision rule fixed before we look.</p>
      <a class="btn btn-primary" href="${REQUEST_FORM_URL}" target="_blank" rel="noopener">Request a test →</a>
    </div>`;
}

const html = signup() + request();
for (const el of document.querySelectorAll("[data-research-cta]")) {
  if (html) { el.innerHTML = html; el.hidden = false; }
}
