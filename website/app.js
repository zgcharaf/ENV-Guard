"use strict";
const scenarios = {
  interpreter: {
    error: "ModuleNotFoundError: No module named 'riskbatch'",
    cause: "WRONG_PYTHON_INTERPRETER",
    confidence: "HIGH · SUPPORTED HYPOTHESIS",
    label: "Controlled GitLab case",
    evidence: [
      "Expected interpreter contains <code>riskbatch</code>",
      "Executed interpreter differs",
      "Executing runtime lacks the package"
    ]
  },
  missing: {
    error: "No module named 'unknown_module'",
    cause: "PYTHON_IMPORT_FAILURE",
    confidence: "LOW · CAUSE UNDETERMINED",
    label: "Illustrative unknown import",
    evidence: [
      "An import failure was observed",
      "No confirmed distribution owner or expected install",
      "Check import name and active Python environment"
    ]
  },
  native: {
    error: "ImportError: libanalytics.so: cannot open shared object file",
    cause: "NATIVE_LIBRARY_LOAD_FAILURE",
    confidence: "OBSERVED FAILURE · ROOT CAUSE UNVERIFIED",
    label: "Illustrative Linux case",
    evidence: [
      "Native dynamic loader error recognized",
      "Inspect library search paths and required symbols",
      "Retest in the intended target runtime"
    ]
  }
};
const all = (selector) => [...document.querySelectorAll(selector)];
const text = (selector, value) => { const el = document.querySelector(selector); if (el) el.textContent = value; };
function switchScenario(name) {
  const scene = scenarios[name];
  if (!scene) return;
  all(".demo-tab").forEach(tab => {
    const active = tab.dataset.case === name;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    if (active) document.getElementById("demo-pane")?.setAttribute("aria-labelledby", tab.id);
  });
  text("#demo-error", scene.error);
  text("#demo-cause", scene.cause);
  text("#demo-confidence", scene.confidence);
  text("#demo-label", scene.label);
  const evidence = document.getElementById("demo-evidence");
  if (evidence) {
    // Only constant, authored markup appears in this static demonstration.
    evidence.innerHTML = scene.evidence.map(value => '<div><span class="t-check">✓</span> ' + value + '</div>').join("");
  }
}
all(".demo-tab").forEach(tab => {
  tab.addEventListener("click", () => switchScenario(tab.dataset.case));
  tab.addEventListener("keydown", ev => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(ev.key)) return;
    ev.preventDefault();
    const tabs = all(".demo-tab");
    const index = tabs.indexOf(tab);
    const next = ev.key === "Home" ? 0 : ev.key === "End" ? tabs.length - 1 : (index + (ev.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length;
    tabs[next].focus();
    switchScenario(tabs[next].dataset.case);
  });
});
const commands = {
  unix: "git clone https://github.com/zgcharaf/ENV-Guard.git\ncd ENV-Guard\npython -m pip install -e .\nenvguard-ci --version",
  windows: "git clone https://github.com/zgcharaf/ENV-Guard.git\ncd ENV-Guard\npy -m pip install -e .\nenvguard-ci --version"
};
let selectedPlatform = "unix";
all(".install-tab").forEach(tab => {
  tab.addEventListener("click", () => {
    selectedPlatform = tab.dataset.platform;
    all(".install-tab").forEach(other => {
      const active = other === tab;
      other.classList.toggle("active", active);
      other.setAttribute("aria-selected", String(active));
      other.tabIndex = active ? 0 : -1;
    });
    document.getElementById("install-code")?.setAttribute("aria-labelledby", tab.id);
    text("#install-text", commands[selectedPlatform]);
    text("#copy-label", "Copy");
  });
  tab.addEventListener("keydown", ev => {
    if (!["ArrowLeft", "ArrowRight"].includes(ev.key)) return;
    ev.preventDefault();
    const options = all(".install-tab");
    const next = options[(options.indexOf(tab) + (ev.key === "ArrowRight" ? 1 : options.length - 1)) % options.length];
    next.focus();
    next.click();
  });
});
async function copyValue(value, button, labelElement) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
    } else {
      const field = document.createElement("textarea");
      field.value = value;
      field.style.cssText = "position:fixed;left:-99999px;top:0";
      document.body.appendChild(field);
      field.focus(); field.select();
      const ok = document.execCommand("copy");
      field.remove();
      if (!ok) throw new Error("Clipboard unavailable");
    }
    if (labelElement) labelElement.textContent = "Copied ✓";
    else if (button) button.textContent = "Copied ✓";
  } catch (_) {
    if (labelElement) labelElement.textContent = "Select to copy";
    else if (button) button.textContent = "Select to copy";
  }
}
document.getElementById("copy-install")?.addEventListener("click", () => {
  copyValue(commands[selectedPlatform], document.getElementById("copy-install"), document.getElementById("copy-label"));
});
document.getElementById("copy-investigate")?.addEventListener("click", ev => {
  copyValue("envguard-ci investigate --project . --report-out report.json -- python -m pytest", ev.currentTarget);
});
