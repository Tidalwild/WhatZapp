import { execFileSync } from "node:child_process";
import { rmSync } from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const zip = path.join(root, "draft-bridge-web.zip");
rmSync(zip, { force: true });
execFileSync("zip", ["-r", "-q", zip, "."], { cwd: path.join(root, "dist"), stdio: "inherit" });
