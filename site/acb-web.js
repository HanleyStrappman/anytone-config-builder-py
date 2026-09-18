//
// Anytone config builder -- the page.
//
// Copyright (C) 2026 Scott Robinson (AG7T)
//
// This program is free software: you can redistribute it and/or modify it under
// the terms of the GNU General Public License as published by the Free Software
// Foundation, either version 3 of the License, or (at your option) any later
// version.  See <https://www.gnu.org/licenses/>.
//
"use strict";

const REQUIRED = ["analog", "digital_others", "digital_repeaters", "talkgroups"];
const OPTIONAL = ["am_air"];
const ROLES = REQUIRED.concat(OPTIONAL);

// Keep in step with MAX_INPUT_FILE_BYTES in builder.py, which is the limit that
// actually applies -- this one only saves reading a file the builder will refuse
// anyway, and saves it landing in the wasm heap on the way.
const MAX_INPUT_BYTES = 10 * 1024 * 1024;

// The format the menu starts on: the layout the original Perl tool wrote, and
// what the builder itself defaults to.
const DEFAULT_FORMAT = "1";

// The two files a CPS format is made of, so a picked file can be checked before
// it is sent rather than after.  Kept in step with CONFIG_FILE_RE in acb_web.py,
// which is the check that actually applies.
const FORMAT_FILE_RE = /^(?:channel-defaults|format)-[A-Za-z0-9_-]+\.csv$/;

// role -> {name, buffer}, or null for "not supplied".
const chosen = {};
ROLES.forEach((role) => { chosen[role] = null; });

let worker = null;
let manifest = null;
let ready = false;
let downloadURL = null;

const el = (id) => document.getElementById(id);

function setStatus(text, kind) {
    const node = el("status");
    node.textContent = text;
    node.className = "status" + (kind ? " status-" + kind : "");
}

function missingInputs() {
    return REQUIRED.filter((role) => chosen[role] === null);
}

function refreshBuildButton() {
    el("build").disabled = !ready || missingInputs().length > 0;
}

// Split from refreshBuildButton so that finishing a build can re-enable the
// button without overwriting what the build had to say -- otherwise the status
// line reads "Ready to build." directly beneath a heading reporting notices.
function announceReadiness() {
    if (!ready) {
        return;
    }
    const missing = missingInputs();
    if (missing.length === 0) {
        setStatus("Ready to build.", "ready");
    } else {
        setStatus(`Waiting for ${missing.length} more file${missing.length === 1 ? "" : "s"}.`);
    }
}

function refreshAndAnnounce() {
    refreshBuildButton();
    announceReadiness();
}

function showChosen(role) {
    const label = el("name-" + role);
    label.textContent = chosen[role] ? chosen[role].name : "";
}

function options() {
    return {
        cps_format: el("cps_format").value,
        sorting: el("sorting").value,
        nicknames: el("nicknames").value,
        hotspot_tx_permit: el("hotspot_tx_permit").value,
    };
}

function humanSize(bytes) {
    if (bytes < 1024) {
        return bytes + " B";
    }
    if (bytes < 1024 * 1024) {
        return (bytes / 1024).toFixed(1) + " KB";
    }
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function clearResults() {
    if (downloadURL) {
        URL.revokeObjectURL(downloadURL);
        downloadURL = null;
    }
    el("results").hidden = true;
    el("results").innerHTML = "";
}

function streamBlock(title, text, kind) {
    if (!text) {
        return null;
    }
    const section = document.createElement("section");
    section.className = "stream stream-" + kind;

    const heading = document.createElement("h3");
    heading.textContent = title;
    section.appendChild(heading);

    const pre = document.createElement("pre");
    pre.textContent = text.replace(/\s+$/, "");
    section.appendChild(pre);

    return section;
}

function showResult(result) {
    clearResults();
    const results = el("results");
    results.hidden = false;

    const heading = document.createElement("h2");

    if (!result.ok) {
        heading.textContent = "Build failed";
        heading.className = "outcome outcome-failed";
        results.appendChild(heading);

        if (result.error) {
            results.appendChild(streamBlock("Problem", result.error, "error"));
        }
        // The builder stops at the first fatal problem and names the file and
        // line it came from, which is the part worth reading.
        const errors = streamBlock("Errors", result.stderr, "error");
        if (errors) {
            results.appendChild(errors);
        }
        const warnings = streamBlock("Warnings", result.stdout, "warning");
        if (warnings) {
            results.appendChild(warnings);
        }
        if (result.crash) {
            results.appendChild(streamBlock("Unexpected error", result.crash, "error"));
        }
        setStatus("Build failed.", "failed");
        return;
    }

    // A build can succeed and still have written to stderr: an over-long name is
    // reported there and then truncated, and the run carries on and exits 0.
    // So the notices are shown, but not as a failure.
    const noticed = Boolean(result.stderr && result.stderr.trim());
    heading.textContent = noticed
        ? `Built ${result.files.length} files, with notices`
        : `Built ${result.files.length} files`;
    heading.className = "outcome outcome-ok";
    results.appendChild(heading);

    const list = document.createElement("ul");
    list.className = "filelist";
    result.files.forEach((file) => {
        const item = document.createElement("li");
        item.innerHTML = "<code></code><span></span>";
        item.querySelector("code").textContent = file.name;
        item.querySelector("span").textContent = humanSize(file.size);
        list.appendChild(item);
    });
    results.appendChild(list);

    downloadURL = URL.createObjectURL(new Blob([result.zip], { type: "application/zip" }));
    const link = document.createElement("a");
    link.className = "download";
    link.href = downloadURL;
    link.download = `codeplug-format${options().cps_format}.zip`;
    link.textContent = "Download .zip";
    results.appendChild(link);

    const notices = streamBlock(
        "Names that had to be shortened", result.stderr, "notice");
    if (notices) {
        results.appendChild(notices);
    }
    const warnings = streamBlock("Warnings", result.stdout, "warning");
    if (warnings) {
        results.appendChild(warnings);
    }

    setStatus(noticed ? "Built, with notices." : "Built.", "ready");
}

async function loadExamples() {
    setStatus("Loading the example set…");
    try {
        for (const role of ROLES) {
            const path = manifest.examples[role];
            if (!path) {
                continue;
            }
            const response = await fetch(new URL(path, window.location.href));
            if (!response.ok) {
                throw new Error(`${path}: ${response.status}`);
            }
            chosen[role] = {
                name: path.split("/").pop(),
                buffer: await response.arrayBuffer(),
            };
            showChosen(role);
        }
    } catch (error) {
        setStatus("Couldn't load the example set: " + error.message, "failed");
        return;
    }
    refreshAndAnnounce();
}

function startBuild() {
    clearResults();
    el("build").disabled = true;

    const files = {};
    const transfer = [];
    ROLES.forEach((role) => {
        if (chosen[role]) {
            // The worker takes ownership of a transferred buffer, so send a copy
            // and keep ours -- the visitor can press Build again without having
            // to pick every file a second time.
            files[role] = chosen[role].buffer.slice(0);
            transfer.push(files[role]);
        }
    });

    worker.postMessage({ type: "build", files: files, options: options() }, transfer);
}

function onWorkerMessage(event) {
    const message = event.data;

    if (message.type === "status") {
        setStatus(message.text);
    } else if (message.type === "ready") {
        ready = true;
        manifestReady(message.version);
        showFormats(message.formats);
        refreshAndAnnounce();
    } else if (message.type === "formats") {
        showFormats(message.formats);
        announceReadiness();
    } else if (message.type === "result") {
        showResult(message.result);
        refreshBuildButton();  // deliberately not announceReadiness()
    } else if (message.type === "failed") {
        setStatus(message.message, "failed");
        refreshBuildButton();
    }
}

function manifestReady(version) {
    el("version").textContent = "anytone-config-builder " + version;
    el("examples").disabled = false;
}

// Rebuilds the format menu from what the builder reports.  Keeps the current
// selection if it still exists, so adding a second format does not silently move
// the visitor off the one they just picked.
function showFormats(report) {
    const select = el("cps_format");
    const keep = select.value;

    select.textContent = "";
    report.formats.forEach((format) => {
        const option = document.createElement("option");
        option.value = format.name;
        option.textContent = format.name + " \u2014 " + format.label
            + (format.tested ? "" : " (untested)");
        select.appendChild(option);
    });

    const names = report.formats.map((format) => format.name);
    select.value = names.includes(keep) ? keep
        : names.includes(DEFAULT_FORMAT) ? DEFAULT_FORMAT
        : names[0];
    select.disabled = report.formats.length === 0;

    // A format file that will not parse leaves the menu standing on whatever
    // shipped, so the visitor can still build while they fix it.
    const note = el("format-added");
    if (report.ok === false) {
        note.textContent = report.error;
        note.className = "note important";
    } else {
        const added = report.formats.filter((format) => format.added);
        note.textContent = added.length === 0 ? ""
            : "Added: " + added.map((format) => format.name).join(", ")
              + ". These have not been checked against a real CPS export "
              + "\u2014 compare what you get back against a codeplug exported "
              + "from your own CPS before trusting it.";
        note.className = "note" + (added.length ? " important" : "");
    }
}

// Sends a picked format file to the worker, which writes it where the builder
// will find it and reports back what that changed.
function addFormatFiles(picked) {
    const files = {};
    const transfer = [];
    const refused = [];

    picked.forEach((file) => {
        if (!FORMAT_FILE_RE.test(file.name)) {
            refused.push(file.name);
            return;
        }
        files[file.name] = file.buffer;
        transfer.push(file.buffer);
    });

    if (refused.length > 0) {
        const note = el("format-added");
        note.textContent = "Not a CPS format file: " + refused.join(", ")
            + ". The name has to be channel-defaults-<name>.csv, or "
            + "format-<name>.csv beside it.";
        note.className = "note important";
        return;
    }

    worker.postMessage({ type: "add_format", files: files }, transfer);
}

async function start() {
    ROLES.forEach((role) => {
        el("file-" + role).addEventListener("change", (event) => {
            const file = event.target.files[0];
            if (!file) {
                chosen[role] = null;
                showChosen(role);
                refreshAndAnnounce();
                return;
            }
            if (file.size > MAX_INPUT_BYTES) {
                chosen[role] = null;
                showChosen(role);
                // Clear the picker too, so its label cannot keep naming a file
                // this page is not holding.
                event.target.value = "";
                // Not refreshAndAnnounce(), which would overwrite this with the
                // "still needed" line before it had been read.
                setStatus(file.name + " is "
                          + humanSize(file.size) + ", over the "
                          + humanSize(MAX_INPUT_BYTES) + " limit.", "failed");
                refreshBuildButton();
                return;
            }
            file.arrayBuffer().then((buffer) => {
                chosen[role] = { name: file.name, buffer: buffer };
                showChosen(role);
                refreshAndAnnounce();
            });
        });
    });

    el("file-format").addEventListener("change", (event) => {
        const picked = Array.from(event.target.files);
        if (picked.length === 0) {
            return;
        }
        const oversized = picked.find((file) => file.size > MAX_INPUT_BYTES);
        if (oversized) {
            el("format-added").textContent = oversized.name + " is "
                + humanSize(oversized.size) + ", over the "
                + humanSize(MAX_INPUT_BYTES) + " limit.";
            el("format-added").className = "note important";
            event.target.value = "";
            return;
        }
        Promise.all(picked.map((file) =>
            file.arrayBuffer().then((buffer) => ({ name: file.name, buffer: buffer }))
        )).then((files) => {
            // Cleared so that re-picking the same file after editing it still
            // fires a change event; the worker already has what was sent.
            event.target.value = "";
            addFormatFiles(files);
        });
    });

    el("build").addEventListener("click", startBuild);
    el("examples").addEventListener("click", loadExamples);

    manifest = await (await fetch(new URL("./manifest.json", window.location.href))).json();

    worker = new Worker(new URL("./acb-worker.js", window.location.href));
    worker.onmessage = onWorkerMessage;
    worker.onerror = (error) => setStatus("Worker failed: " + error.message, "failed");
    worker.postMessage({ type: "boot" });

    setStatus("Starting…");
}

start();
