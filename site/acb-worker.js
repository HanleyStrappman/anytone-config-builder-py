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
let pyStagingPath = null;
let pyAddFormat = null;
let pyFormats = null;

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

// What to tell the page about something thrown.  An Emscripten filesystem
// error is not an Error and has no message, only an errno; String() of it is
// "[object Object]", which says nothing.
function describe(error) {
    if (error && error.message) {
        return error.message;
    }
    if (error && typeof error.errno === "number") {
        return "Filesystem error " + error.errno;
    }
    return String(error);
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
    pyStagingPath = pyodide.globals.get("staging_path");
    pyAddFormat = pyodide.globals.get("add_format");
    pyFormats = pyodide.globals.get("formats");

    // The page's format menu is whatever the builder found, rather than a list
    // kept in the HTML: a CPS format is a file in the config directory now, so
    // the only thing that actually knows what formats exist is the builder.
    post("ready", { version: manifest.version, formats: JSON.parse(pyFormats()) });
}

// A CPS format the visitor supplied: a channel layout, and optionally the format
// file beside it.  Staged, then handed to add_format(), which moves it into the
// config directory only once the builder has read it and found it good -- and
// puts back whatever was there if not, so a bad upload changes nothing.  The
// config directory is the one pyReset() does not empty, so a format added once
// survives every build in this tab -- and nothing beyond it, since the
// filesystem goes when the tab does.
function addFormat(message) {
    status("Reading the format\u2026");

    const names = Object.keys(message.files);
    for (const name of names) {
        // staging_path() refuses a name that is not one of a format's two files,
        // which is also what stops it landing anywhere but the staging directory.
        pyodide.FS.writeFile(pyStagingPath(name), new Uint8Array(message.files[name]));
    }

    post("formats", { formats: JSON.parse(pyAddFormat(JSON.stringify(names))) });
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
        } else if (event.data.type === "add_format") {
            addFormat(event.data);
        }
    } catch (error) {
        post("failed", { message: describe(error) });
    }
};
