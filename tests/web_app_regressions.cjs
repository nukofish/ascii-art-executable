const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../codeart/web/app.js"), "utf8");
const flush = () => new Promise(resolve => setTimeout(resolve, 0));

function element() {
  return {
    value: "", checked: false, hidden: false, disabled: false,
    textContent: "", children: [], listeners: {},
    style: {setProperty() {}},
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = [...children]; },
    addEventListener(type, handler) {
      (this.listeners[type] ||= []).push(handler);
    },
    dispatchEvent(event) {
      return Promise.all((this.listeners[event.type] || []).map(handler => handler(event)));
    },
    get childElementCount() { return this.children.length; }
  };
}

function response(data) {
  return {ok: true, status: 200, json: async () => data};
}

function openPage(previous, handler) {
  const nodes = new Map();
  const get = id => {
    if (!nodes.has(id)) nodes.set(id, element());
    return nodes.get(id);
  };
  get("shape").value = "circle";
  get("scale").value = "1";
  const storage = new Map(previous ? [["codeart-job", previous]] : []);
  vm.runInNewContext(source, {
    document: {
      getElementById: get, createElement: element, documentElement: element()
    },
    Option: function(text, value) { this.textContent = text; this.value = value; },
    Event: function(type) { this.type = type; },
    sessionStorage: {
      getItem: key => storage.get(key),
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key)
    },
    window: {setTimeout() {}},
    fetch: async (url, options = {}) => {
      if (url === "/api/samples") return response([]);
      if (url === "/api/environment") return response({});
      return handler(url, options);
    }
  });
  return get;
}

function completedJob() {
  return {
    id: "file-job", state: "finished", elapsed_s: 0.1,
    source: "int f(void){return 1;}",
    input_source: "#include <stdio.h>\nint f(void){return 1;}\n",
    file_mode: true, function: "f", sample: null, shape: "circle", scale: 1,
    result: {
      status: "OK", verified: true, source_text: "int f(void){return 1;}\n",
      layout: {width: 64, height: 32, scale: 1, attempts: 1},
      font_id: "Roboto Mono Regular", cell_aspect: 0.5,
      coverage: {total: 0.99}, code_fill_ratio: 0.01,
      attempt_history: [], diagnostics: [], verification: null,
      checks: {
        token: {status: "PASS"}, geometry: {status: "PASS"},
        compile: {status: "PASS"}, behavior: {status: "NOT_RUN", reason: "NO_FIXTURE"}
      },
      prepass: {
        selected: "f", error: null,
        candidates: [{name: "f", start_line: 2, end_line: 2, a_status: "PASS"}]
      }
    }
  };
}

async function run() {
  const job = completedJob();
  const restored = openPage(job.id, async () => response(job));
  await flush();
  assert.equal(restored("source").value, job.input_source);
  assert.equal(restored("file-mode").checked, true);
  assert.equal(restored("file-scope").hidden, false);
  assert.equal(restored("function").value, "f");
  assert.equal(restored("candidates").hidden, false);

  const stopped = completedJob();
  stopped.result.status = "CANCELLED";
  stopped.result.verified = false;
  stopped.result.prepass = null;
  const stoppedPage = openPage(stopped.id, async () => response(stopped));
  await flush();
  assert.equal(stoppedPage("source").value, stopped.input_source);
  assert.equal(stoppedPage("file-mode").checked, true);
  assert.equal(stoppedPage("file-scope").hidden, false);
  assert.equal(stoppedPage("function").value, "f");

  const failed = completedJob();
  failed.result.status = "FAILED";
  failed.result.verified = false;
  failed.result.source_text = null;
  failed.result.layout = null;
  failed.result.prepass.error = "NO_ELIGIBLE_FUNCTION";
  failed.result.prepass.selected = null;
  failed.result.prepass.candidates[0].a_status = "FAIL";
  const failurePage = openPage(failed.id, async () => response(failed));
  await flush();
  assert.equal(failurePage("diagnostics").hidden, false);
  assert.match(failurePage("diagnostics").children[0].textContent, /NO_ELIGIBLE_FUNCTION/);
  assert.equal(failurePage("report").hidden, false);

  const calls = [];
  let acceptSubmission;
  const page = openPage(null, async (url, options) => {
    calls.push(url);
    if (url === "/api/generate") {
      return new Promise(resolve => { acceptSubmission = resolve; });
    }
    if (url.endsWith("/cancel")) return response({cancel_requested: true});
    return response(job);
  });
  await flush();
  page("source").value = job.input_source;
  page("file-mode").checked = true;
  const pending = page("generator").dispatchEvent({type: "submit", preventDefault() {}});
  await flush();
  await page("cancel").dispatchEvent({type: "click"});
  acceptSubmission(response({id: job.id}));
  await pending;
  await flush();
  assert.equal(calls.filter(url => url.endsWith("/cancel")).length, 1);
  console.log("4 web application regressions passed");
}

module.exports = run;
if (require.main === module) {
  run().catch(error => {
    console.error(error);
    process.exitCode = 1;
  });
}
