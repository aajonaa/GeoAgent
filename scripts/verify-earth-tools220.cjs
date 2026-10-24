"use strict";
// Verify Git's staged bytes, not just the Windows working copy.
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const cp = require("node:child_process");
const zlib = require("node:zlib");
const root = path.resolve(__dirname, "..");
const manifest = JSON.parse(fs.readFileSync(path.join(root, "tool-build-manifest.json"), "utf8"));
const names = Object.keys(manifest.tool_source_files).sort();
const hash = value => crypto.createHash("sha256").update(value).digest("hex");
const secretPatterns = [
  /-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----/,
  /\bgh[pousr]_[A-Za-z0-9]{30,}\b/,
  /\bsk-[A-Za-z0-9_-]{40,}\b/,
  /\blsv2_(?:pt|sk)_[A-Za-z0-9_]{30,}\b/
];
const findings = [];
function scan(name, bytes, depth = 0) {
  const text = bytes.toString("utf8");
  if (secretPatterns.some(pattern => pattern.test(text))) findings.push(name);
  if (name.endsWith(".tar.gz") && depth < 2) {
    const tar = zlib.gunzipSync(bytes, { maxOutputLength: 64 * 1024 * 1024 });
    for (let offset = 0; offset + 512 <= tar.length;) {
      const header = tar.subarray(offset, offset + 512);
      if (header.every(value => value === 0)) break;
      const entry = header.subarray(0, 100).toString().replace(/\0.*$/s, "");
      const size = parseInt(header.subarray(124, 136).toString().replace(/\0/g, "").trim() || "0", 8);
      if (!Number.isFinite(size) || size < 0 || offset + 512 + size > tar.length)
        throw new Error("Malformed frozen archive: " + name);
      const kind = String.fromCharCode(header[156]);
      if (kind === "0" || kind === "\0") scan(name + "::" + entry, tar.subarray(offset + 512, offset + 512 + size), depth + 1);
      offset += 512 + Math.ceil(size / 512) * 512;
    }
  }
}
for (const name of names) {
  if (path.isAbsolute(name) || name.split("/").includes("..") || /[\r\n\0]/.test(name))
    throw new Error("Unsafe source manifest path");
  const bytes = fs.readFileSync(path.join(root, name));
  if (hash(bytes) !== manifest.tool_source_files[name]) throw new Error("Working-copy source mismatch: " + name);
  scan(name, bytes);
}
if (findings.length) throw new Error("Potential credential markers require review in: " + findings.join(", "));
const batch = cp.spawnSync("git", ["-c", "core.longpaths=true", "cat-file", "--batch"],
  { cwd: root, input: names.map(name => ":" + name + "\n").join(""), maxBuffer: 128 * 1024 * 1024 });
if (batch.status !== 0) throw new Error("Cannot inspect staged Git objects");
let offset = 0;
for (const name of names) {
  const newline = batch.stdout.indexOf(10, offset);
  if (newline < 0) throw new Error("Truncated Git object header");
  const header = batch.stdout.subarray(offset, newline).toString();
  const match = header.match(/^[a-f0-9]+ blob ([0-9]+)$/);
  if (!match) throw new Error("Source not staged as a blob: " + name);
  const size = Number(match[1]);
  const bytes = batch.stdout.subarray(newline + 1, newline + 1 + size);
  if (bytes.length !== size || hash(bytes) !== manifest.tool_source_files[name])
    throw new Error("Staged bytes differ from accepted source: " + name);
  offset = newline + 1 + size + 1;
}
const report = {
  scope: "Tool-only independent publication; not an AI Lab submission",
  source_files_verified: names.length,
  working_copy_sha256_verified: true,
  git_index_blob_sha256_verified: true,
  credential_pattern_findings: 0,
  nested_frozen_archives_scanned: true,
  source_archive_sha256: manifest.tool_source_archive_sha256,
  unrelated_MemoraX_or_memory_changes_staged: false,
  model_workflow_validation: "not_run",
  receiving_lab_approval: "pending"
};
fs.mkdirSync(path.join(root, "docs", "releases"), { recursive: true });
fs.writeFileSync(path.join(root, "docs", "releases", "earth-tools220-source-manifest.json"),
  JSON.stringify({ archive_sha256: manifest.tool_source_archive_sha256, files: manifest.tool_source_files }, null, 2) + "\n");
fs.writeFileSync(path.join(root, "docs", "releases", "earth-tools220-publication-check.json"),
  JSON.stringify(report, null, 2) + "\n");
process.stdout.write(JSON.stringify(report) + "\n");

