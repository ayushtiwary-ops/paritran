// Pyodide bootstrap and engine run, in a module Web Worker so the one-time
// runtime download never blocks the page (SPEC_HOSTED_APP 2.3). Same-origin
// vendored files first; pinned jsDelivr v314.0.2 as fallback only. The engine
// (docs/app/py/paritran_prototype.py, a byte-identical copy of
// src/paritran_prototype.py) runs unmodified except for the single seed line;
// results are written to the in-browser MEMFS, never to the repository file.

const WHEEL = "networkx-3.6.1-py3-none-any.whl";

type RunMessage = {
  type: "run";
  seed: number;
  vendorBase: string;
  cdnBase: string;
  pyUrl: string;
};

// The DOM lib types `self` as a Window; in a worker it is a
// DedicatedWorkerGlobalScope. Cast once to the two members we use so the file
// stays strict-clean without pulling the WebWorker lib into the app program.
const workerScope = self as unknown as {
  postMessage: (message: unknown) => void;
  onmessage: ((event: MessageEvent<RunMessage>) => void) | null;
};

type Pyodide = {
  FS: {
    mkdirTree: (path: string) => void;
    writeFile: (path: string, data: string) => void;
    unlink: (path: string) => void;
  };
  loadPackage: (url: string) => Promise<void>;
  runPythonAsync: (code: string) => Promise<string>;
};

let pyodide: Pyodide | null = null;
let loadedFrom: "same-origin" | "cdn" | null = null;

function post(message: unknown): void {
  workerScope.postMessage(message);
}

async function primeWithProgress(url: string, label: string): Promise<void> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`fetch ${label} failed with HTTP ${response.status}`);
  }
  const total = Number(response.headers.get("content-length") ?? 0);
  const reader = response.body?.getReader();
  if (!reader) {
    await response.arrayBuffer();
    post({ type: "progress", label, loaded: total, total });
    return;
  }
  let loaded = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    loaded += value ? value.length : 0;
    post({ type: "progress", label, loaded, total });
  }
}

async function loadFrom(indexURL: string, source: "same-origin" | "cdn"): Promise<void> {
  post({ type: "stage", stage: `fetching the Python runtime (${source})` });
  // Prime the HTTP cache with real byte-level progress so loadPyodide hits cache.
  await primeWithProgress(indexURL + "pyodide.asm.wasm", "python runtime");
  await primeWithProgress(indexURL + "python_stdlib.zip", "standard library");
  await primeWithProgress(indexURL + WHEEL, "networkx");
  post({ type: "stage", stage: "starting Python (about 2 s)" });
  const mod = (await import(/* @vite-ignore */ indexURL + "pyodide.mjs")) as {
    loadPyodide: (options: { indexURL: string }) => Promise<Pyodide>;
  };
  const instance = await mod.loadPyodide({ indexURL });
  post({ type: "stage", stage: "loading networkx (under 1 s)" });
  // Direct wheel URL only. Resolving the package by name would pull the
  // matplotlib and numpy closure (tens of MB). Acceptance check A6.
  await instance.loadPackage(indexURL + WHEEL);
  pyodide = instance;
  loadedFrom = source;
}

async function ensurePyodide(vendorBase: string, cdnBase: string): Promise<void> {
  if (pyodide) return;
  try {
    await loadFrom(vendorBase, "same-origin");
  } catch {
    post({
      type: "stage",
      stage: "same-origin runtime unavailable, using the pinned CDN fallback",
    });
    await loadFrom(cdnBase, "cdn");
  }
}

async function run(message: RunMessage): Promise<void> {
  await ensurePyodide(message.vendorBase, message.cdnBase);
  const active = pyodide;
  if (!active) {
    throw new Error("the Python runtime failed to initialise");
  }
  post({ type: "stage", stage: "running the engine" });
  const sourceResponse = await fetch(message.pyUrl);
  if (!sourceResponse.ok) {
    throw new Error(`engine source fetch failed with HTTP ${sourceResponse.status}`);
  }
  const source = await sourceResponse.text();
  const needle = "random.seed(42)";
  const occurrences = source.split(needle).length - 1;
  if (occurrences !== 1) {
    throw new Error(
      `seed-patch guard: expected exactly one "${needle}" in the engine source, found ${occurrences}. Refusing to run on drifted source.`,
    );
  }
  const patched = source.replace(needle, `random.seed(${message.seed})`);
  const fs = active.FS;
  fs.mkdirTree("/home/pyodide/src");
  fs.writeFile("/home/pyodide/src/paritran_prototype.py", patched);
  try {
    fs.unlink("/home/pyodide/results.json");
  } catch {
    // No prior results on the first run; nothing to remove.
  }
  const program = [
    "import runpy",
    "runpy.run_path('/home/pyodide/src/paritran_prototype.py', run_name='__main__')",
    "open('/home/pyodide/results.json').read()",
  ].join("\n");
  const resultJson = await active.runPythonAsync(program);
  const results = JSON.parse(resultJson) as Record<string, number | string | boolean>;
  post({ type: "result", seed: message.seed, results, loadedFrom });
}

workerScope.onmessage = (event: MessageEvent<RunMessage>): void => {
  const message = event.data;
  if (!message || message.type !== "run") return;
  run(message).catch((error: unknown) => {
    post({ type: "error", message: error instanceof Error ? error.message : String(error) });
  });
};
