// Drive a real browser over the DevTools Protocol, with no dependencies.
//
// A dashboard here is a static page the server hands over untouched: Python never parses
// it, so a reference error leaves a blank panel and every test stays green. `node --check`
// catches a syntax error and nothing catches "the renderer read a field that is not there"
// or "the button is wired to a selector that does not exist".
//
// So this opens the page in headless Chrome, clicks what a reader would click, waits for
// the thing that should appear, and fails loudly when it does not. Node 22+ has a global
// WebSocket, and Chrome ships the protocol, so the whole client is the file you are
// reading.
//
//   node scripts/ui_smoke.mjs <chrome-path> <plan.json>
//
// The plan is {"url": ..., "steps": [...]}, where a step is one of:
//   {"waitFor": "#sel"}                wait for the selector to exist
//   {"click": "#sel"}                  click it
//   {"select": "#sel", "value": "x"}   set a <select> and fire change
//   {"expectText": "#sel", "contains": "..."}   assert the element's text
//   {"fill": "#sel", "value": "x"}     type into an input or textarea
//   {"js": "return ...", "expect": v}   run an expression and compare its value
//   {"expectNoEmpty": ["#a", "#b"]}    assert each element has rendered something
//   {"screenshot": "path.png", "of": "#sel"}   save a PNG, clipped to that element
//   {"clickAll": "[role=tab]", "requirePanelText": 40, "auditAfterEach": [...]}
//                                      open every tab in turn, and on each one check the
//                                      panel it controls has text and audit what is shown
//   {"audit": ["undefined", "NaN"]}     fail if any visible panel shows one of these
//
// Console errors and page exceptions fail the run whatever else happens, because a panel
// that throws halfway through still looks finished.

import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [chromePath, planPath] = process.argv.slice(2);
if (!chromePath || !planPath) {
  console.error("usage: node scripts/ui_smoke.mjs <chrome> <plan.json>");
  process.exit(2);
}

const plan = JSON.parse(await readFile(planPath, "utf8"));
const port = 9222 + Math.floor(Math.random() * 500);
const profile = await mkdtemp(join(tmpdir(), "rankloom-ui-"));

const chrome = spawn(
  chromePath,
  [
    "--headless=new",
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--disable-background-networking",
    `--window-size=${process.env.UI_WIDTH || 1280},1600`,
    `--user-data-dir=${profile}`,
    `--remote-debugging-port=${port}`,
    "about:blank",
  ],
  { stdio: ["ignore", "ignore", "pipe"] },
);
let chromeStderr = "";
chrome.stderr.on("data", (chunk) => {
  chromeStderr += String(chunk);
});

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function endpoint() {
  for (let attempt = 0; attempt < 60; attempt++) {
    try {
      const reply = await fetch(`http://127.0.0.1:${port}/json/version`);
      const body = await reply.json();
      if (body.webSocketDebuggerUrl) return body.webSocketDebuggerUrl;
    } catch {
      // Chrome is still starting.
    }
    await sleep(250);
  }
  throw new Error(`Chrome never opened a debugging port.\n${chromeStderr.slice(-800)}`);
}

class Session {
  constructor(socket) {
    this.socket = socket;
    this.id = 0;
    this.pending = new Map();
    this.sessionId = null;
    this.problems = [];
    socket.addEventListener("message", (event) => this.receive(JSON.parse(event.data)));
  }

  receive(message) {
    if (message.id && this.pending.has(message.id)) {
      const { resolve, reject } = this.pending.get(message.id);
      this.pending.delete(message.id);
      if (message.error) reject(new Error(message.error.message));
      else resolve(message.result);
      return;
    }
    if (message.method === "Runtime.exceptionThrown") {
      const details = message.params.exceptionDetails;
      this.problems.push(
        `page threw: ${details.exception?.description || details.text}`.split("\n")[0],
      );
    }
    if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") {
      const text = message.params.args.map((arg) => arg.value ?? arg.description).join(" ");
      this.problems.push(`console error: ${text}`);
    }
    // A Content-Security-Policy refusal is not a console.error call: Chrome reports it in the
    // Log domain, so a page whose styles or scripts the policy blocked would otherwise pass.
    if (message.method === "Log.entryAdded" && message.params.entry.level === "error") {
      const entry = message.params.entry;
      if (!/favicon\.ico/.test(entry.url || "") && !/status of 40[19]/.test(entry.text)) {
        this.problems.push(`browser log: ${entry.text}`.split("\n")[0]);
      }
    }
  }

  send(method, params = {}) {
    const id = ++this.id;
    const payload = { id, method, params };
    if (this.sessionId) payload.sessionId = this.sessionId;
    this.socket.send(JSON.stringify(payload));
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error(`${method} timed out`));
        }
      }, 60_000);
    });
  }

  async evaluate(expression) {
    const result = await this.send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.exception?.description || "evaluate failed");
    }
    return result.result.value;
  }
}

// Scan what is actually on screen for the strings that mean a renderer went wrong. A page
// that prints "undefined" or "NaN" is not a page that failed loudly - it looks finished,
// and only reading it catches that.
async function audit(session, forbid) {
  const problems = await session.evaluate(
    `(() => {
      const needles = ${JSON.stringify(forbid)};
      const out = [];
      const visible = (node) => {
        const box = node.getBoundingClientRect();
        return box.width > 0 || box.height > 0;
      };
      const panels = document.querySelectorAll("section, .card, .tile, table, dl");
      for (const panel of panels) {
        if (!visible(panel)) continue;
        // Doubled backslash: this runs inside a template literal, where a single "\s"
        // arrives in the page as a plain "s" and the regex deletes every letter s.
        const text = (panel.innerText || "").replace(/\\s+/g, " ").trim();
        for (const needle of needles) {
          const at = text.indexOf(needle);
          if (at < 0) continue;
          out.push(needle + " in: " + text.slice(Math.max(0, at - 60), at + 60));
        }
      }
      return [...new Set(out)].slice(0, 12);
    })()`,
  );
  return problems || [];
}

const socketUrl = await endpoint();
const socket = new WebSocket(socketUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve);
  socket.addEventListener("error", () => reject(new Error("could not attach to Chrome")));
});
const session = new Session(socket);

const { targetId } = await session.send("Target.createTarget", { url: "about:blank" });
const attached = await session.send("Target.attachToTarget", { targetId, flatten: true });
session.sessionId = attached.sessionId;
await session.send("Runtime.enable");
await session.send("Page.enable");
await session.send("Log.enable");

const failures = [];
const log = [];

try {
  await session.send("Page.navigate", { url: plan.url });
  await session.evaluate(
    `new Promise((done) => {
      if (document.readyState === "complete") return done(true);
      window.addEventListener("load", () => done(true), { once: true });
    })`,
  );
  // The boot function is async, so give it a moment to finish its first fetches.
  await sleep(plan.settle ?? 1200);

  for (const step of plan.steps) {
    if (step.waitFor) {
      const ok = await session.evaluate(
        `new Promise((done) => {
          const started = Date.now();
          const tick = () => {
            const node = document.querySelector(${JSON.stringify(step.waitFor)});
            if (node && (node.children.length || (node.textContent || "").trim())) return done(true);
            if (Date.now() - started > ${step.timeout ?? 30000}) return done(false);
            setTimeout(tick, 150);
          };
          tick();
        })`,
      );
      if (!ok) failures.push(`nothing rendered into ${step.waitFor}`);
      else log.push(`rendered ${step.waitFor}`);
      continue;
    }
    if (step.click) {
      const ok = await session.evaluate(
        `(() => {
          const node = document.querySelector(${JSON.stringify(step.click)});
          if (!node) return false;
          node.click();
          return true;
        })()`,
      );
      if (!ok) failures.push(`no element to click at ${step.click}`);
      else log.push(`clicked ${step.click}`);
      await sleep(step.after ?? 250);
      continue;
    }
    if (step.select) {
      const ok = await session.evaluate(
        `(() => {
          const node = document.querySelector(${JSON.stringify(step.select)});
          if (!node) return false;
          node.value = ${JSON.stringify(step.value)};
          node.dispatchEvent(new Event("change", { bubbles: true }));
          return node.value === ${JSON.stringify(step.value)};
        })()`,
      );
      if (!ok) failures.push(`could not set ${step.select} to ${step.value}`);
      else log.push(`set ${step.select} = ${step.value}`);
      continue;
    }
    if (step.fill) {
      const ok = await session.evaluate(
        `(() => {
          const node = document.querySelector(${JSON.stringify(step.fill)});
          if (!node) return false;
          node.value = ${JSON.stringify(step.value)};
          node.dispatchEvent(new Event("input", { bubbles: true }));
          node.dispatchEvent(new Event("change", { bubbles: true }));
          return node.value === ${JSON.stringify(step.value)};
        })()`,
      );
      if (!ok) failures.push(`could not type into ${step.fill}`);
      else log.push(`typed ${String(step.value).length} characters into ${step.fill}`);
      continue;
    }
    if (step.js) {
      let value;
      try {
        // Wrapped in an async function so a probe can await: reading a panel that fetches
        // means waiting for the fetch, and the non-async wrapper made that a syntax error
        // rather than a missing feature.
        value = await session.evaluate(`(async () => { ${step.js} })()`);
      } catch (error) {
        failures.push(`${step.label || "probe"} threw: ${error.message}`);
        continue;
      }
      const wanted = step.expect ?? true;
      if (JSON.stringify(value) !== JSON.stringify(wanted)) {
        failures.push(
          `${step.label || "probe"}: expected ${JSON.stringify(wanted)}, got ${JSON.stringify(value)}`,
        );
      } else {
        log.push(`${step.label || "probe"} = ${JSON.stringify(value)}`);
      }
      await sleep(step.after ?? 0);
      continue;
    }
    if (step.expectText) {
      const text = await session.evaluate(
        `(document.querySelector(${JSON.stringify(step.expectText)}) || {}).textContent || ""`,
      );
      if (!String(text).includes(step.contains)) {
        failures.push(
          `${step.expectText} does not contain ${JSON.stringify(step.contains)}; it has ` +
            JSON.stringify(String(text).trim().slice(0, 160)),
        );
      } else {
        log.push(`${step.expectText} contains ${JSON.stringify(step.contains)}`);
      }
      continue;
    }
    if (step.clickAll) {
      // Wait for the first match rather than asking once: the zero that started this was
      // a page still coming up, not a page without tabs, and a check that fails when the
      // machine is busy teaches people to ignore it.
      const count = await session.evaluate(
        `new Promise((done) => {
          const started = Date.now();
          const tick = () => {
            const found = document.querySelectorAll(${JSON.stringify(step.clickAll)}).length;
            if (found) return done(found);
            if (Date.now() - started > ${step.timeout ?? 10000}) return done(0);
            setTimeout(tick, 150);
          };
          tick();
        })`,
      );
      // Nothing to click is not nothing to report. One audit run came back "ok, 0 checks"
      // because the sweep found no tabs on a page that has three, and a pass that checked
      // nothing is worse than a failure: it is a failure that looks like a pass.
      if (!count && !step.allowNone) {
        failures.push(`nothing matched ${step.clickAll}, so nothing was clicked`);
        continue;
      }
      for (let index = 0; index < count; index++) {
        const label = await session.evaluate(
          `(() => {
            const nodes = document.querySelectorAll(${JSON.stringify(step.clickAll)});
            const node = nodes[${index}];
            if (!node) return null;
            node.click();
            return (node.textContent || "").trim();
          })()`,
        );
        if (label === null) {
          failures.push(`${step.clickAll}[${index}] disappeared while clicking through`);
          continue;
        }
        log.push(`opened "${label}"`);
        await sleep(step.after ?? 400);
        if (step.requirePanelText) {
          const state = await session.evaluate(
            `(() => {
              const nodes = document.querySelectorAll(${JSON.stringify(step.clickAll)});
              const node = nodes[${index}];
              const id = node && node.getAttribute("aria-controls");
              if (!id) return "no panel named";
              const panel = document.getElementById(id);
              if (!panel) return "panel " + id + " does not exist";
              const text = (panel.innerText || "").trim();
              return text.length >= ${step.requirePanelText} ? "filled" : "only " + text.length + " characters of text";
            })()`,
          );
          if (state !== "filled") failures.push(`panel behind "${label}": ${state}`);
        }
        if (step.auditAfterEach) {
          const found = await audit(session, step.auditAfterEach);
          for (const item of found) failures.push(`on "${label}": ${item}`);
        }
      }
      continue;
    }
    if (step.screenshot) {
      // Clipped to an element when one is named: a full-page shot of a dashboard is mostly
      // chrome, and a screenshot in a repository has to earn its bytes.
      let clip = null;
      if (step.of) {
        clip = await session.evaluate(
          `(() => {
            const node = document.querySelector(${JSON.stringify(step.of)});
            if (!node) return null;
            const box = node.getBoundingClientRect();
            return JSON.stringify({
              x: Math.max(box.x + window.scrollX - 12, 0),
              y: Math.max(box.y + window.scrollY - 12, 0),
              width: Math.min(box.width + 24, 1280),
              height: Math.min(box.height + 24, 2000),
              scale: 1,
            });
          })()`,
        );
        if (!clip) {
          failures.push(`nothing to photograph at ${step.of}`);
          continue;
        }
        clip = JSON.parse(clip);
      }
      const shot = await session.send("Page.captureScreenshot", {
        format: "png",
        captureBeyondViewport: Boolean(clip),
        ...(clip ? { clip } : {}),
      });
      await writeFile(step.screenshot, Buffer.from(shot.data, "base64"));
      log.push(`photographed ${step.of || "the page"} into ${step.screenshot}`);
      continue;
    }
    if (step.audit) {
      const found = await audit(session, step.audit);
      for (const item of found) failures.push(item);
      if (!found.length) log.push("nothing suspicious in the visible text");
      continue;
    }
    if (step.expectNoEmpty) {
      for (const selector of step.expectNoEmpty) {
        const filled = await session.evaluate(
          `(() => {
            const node = document.querySelector(${JSON.stringify(selector)});
            if (!node) return "missing";
            return (node.children.length || (node.textContent || "").trim()) ? "filled" : "empty";
          })()`,
        );
        if (filled !== "filled") failures.push(`${selector} is ${filled}`);
        else log.push(`${selector} is filled`);
      }
    }
  }
} catch (error) {
  failures.push(String(error.message || error));
} finally {
  socket.close();
  chrome.kill();
  await rm(profile, { recursive: true, force: true }).catch(() => {});
}

const problems = [...new Set(session.problems)];
console.log(JSON.stringify({ ok: !failures.length && !problems.length, log, failures, problems }, null, 2));
process.exit(failures.length || problems.length ? 1 : 0);
