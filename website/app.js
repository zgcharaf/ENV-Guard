"use strict";

/* Progressive enhancement for the academic website. No network requests. */
const copyButtons = [...document.querySelectorAll("button.copy")];

function getCommand(button) {
  const code = button.closest(".code-example")?.querySelector("pre code");
  return code ? code.textContent.trim() : "";
}

async function copyToClipboard(value) {
  if (!value) return false;
  try {
    if (!navigator.clipboard || !window.isSecureContext) throw new Error("No secure Clipboard API");
    await navigator.clipboard.writeText(value);
    return true;
  } catch (_) {
    // Fallback for local file:// previews and older browsers.
    const field = document.createElement("textarea");
    field.value = value;
    field.style.position = "fixed";
    field.style.left = "-10000px";
    field.setAttribute("aria-hidden", "true");
    document.body.append(field);
    field.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (_) { ok = false; }
    field.remove();
    return ok;
  }
}
copyButtons.forEach(button => button.addEventListener("click", async () => {
  const initial = button.textContent;
  const ok = await copyToClipboard(getCommand(button));
  button.textContent = ok ? "Copied" : "Select to copy";
  window.setTimeout(() => { button.textContent = initial; }, 1800);
}));

// Support direct links to documentation anchors without client-side routing.
document.querySelectorAll('a[href^="#"]').forEach(link => {
  link.addEventListener("click", () => {
    const id = link.getAttribute("href").slice(1);
    const destination = document.getElementById(id);
    if (destination) destination.setAttribute("tabindex", "-1");
  });
});
