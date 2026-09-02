//
// Anytone config builder -- the worker that owns Pyodide.
//
// Copyright (C) 2026 Scott Robinson (AG7T)
//
// This program is free software: you can redistribute it and/or modify it under
// the terms of the GNU General Public License as published by the Free Software
// Foundation, either version 3 of the License, or (at your option) any later
// version.  See <https://www.gnu.org/licenses/>.
//
// Python runs here rather than on the page's thread.  The repeater matrix is
// multiplied out into one channel per repeater per talkgroup -- the PNW example
// set comes to a 632KB channel file -- and a build that long on the main thread
// would freeze the tab, spinner and all.  Off the main thread the page stays
// responsive and a build that goes wrong cannot take the window with it.
//
// The boundary is deliberately dull: the page sends bytes and options, gets back
// the parsed result and a zip.  See acb_web.py for the other half.
//
"use strict";

// Where the wheel is unpacked, and what gets put on sys.path.
const PACKAGE_DIRECTORY = "/wheel";

let pyodide = null;
let manifest = null;
let pyBuild = null;
let pyReset = null;
let pyInputPath = null;

// Resolved against this worker's own URL rather than the server root, so the
// site works unchanged at a domain root, in a subdirectory, or under the
// /<repo>/ path GitHub Pages serves a project from.
function siteURL(path) {
    return new URL(path, self.location.href).href;
}

function post(type, payload, transfer) {
    self.postMessage(Object.assign({ type: type }, payload), transfer || []);
}

function status(text) {
    post("status", { text: text });
}

async function fetchSite(path) {
    const response = await fetch(siteURL(path));
    if (!response.ok) {
        throw new Error(`Couldn't fetch ${path}: ${response.status} ${response.statusText}`);
    }
    return response;
}

async function boot() {
    manifest = await (await fetchSite("./manifest.json")).json();

    const indexURL = siteURL(manifest.pyodide.indexURL);
    status("Downloading Python…");
    importScripts(indexURL + "pyodide.js");

    // eslint-disable-next-line no-undef
    pyodide = await loadPyodide({ indexURL: indexURL });

    status("Installing the builder…");

    // The wheel is a zip of pure Python with no dependencies, so it is simply
    // unpacked onto sys.path.  micropip would work too, but it is a second
    // download and a resolver we have nothing for it to resolve -- and doing
    // without it means a self-hosted Pyodide needs only the 6MB core build
    // rather than the 392MB full distribution.
    const wheel = await (await fetchSite(manifest.wheel)).arrayBuffer();
    pyodide.FS.mkdirTree(PACKAGE_DIRECTORY);
    await pyodide.unpackArchive(wheel, "zip", { extractDir: PACKAGE_DIRECTORY });
    pyodide.runPython(
        `import sys; sys.path.insert(0, ${JSON.stringify(PACKAGE_DIRECTORY)})`);

    pyodide.runPython(await (await fetchSite("./acb_web.py")).text());
    pyBuild = pyodide.globals.get("build");
    pyReset = pyodide.globals.get("reset");
    pyInputPath = pyodide.globals.get("input_path");

    post("ready", { version: manifest.version });
}

function runBuild(message) {
    status("Building…");

    // Clears both working directories, so a second build in the same tab cannot
    // inherit an input or an output file from the first.
    pyReset();

    for (const role of Object.keys(message.files)) {
        pyodide.FS.writeFile(pyInputPath(role), new Uint8Array(message.files[role]));
    }

    const result = JSON.parse(pyBuild(JSON.stringify(message.options)));

    let transfer = [];
    if (result.ok) {
        // slice() to get a buffer sized to just this file, which can then be
        // handed to the page rather than copied.
        result.zip = pyodide.FS.readFile(result.zip_path).slice().buffer;
        transfer = [result.zip];
    }

    post("result", { result: result }, transfer);
}

self.onmessage = async (event) => {
    try {
        if (event.data.type === "boot") {
            await boot();
        } else if (event.data.type === "build") {
            runBuild(event.data);
        }
    } catch (error) {
        post("failed", { message: error && error.message ? error.message : String(error) });
    }
};
