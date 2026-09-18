/**
 * 4p: a four-pane advisory panel in the current Herdr tab.
 *
 * Registers /4p. The panel launcher lives in panel/4p.py and is resolved
 * relative to this file, so the package works from a git install, an npm
 * install, or a local path without any hardcoded home directory.
 *
 * The four seats:
 *   AMO (contraire)  critical eye, constructive contradiction
 *   tester           empirical verification only
 *   reviewer         the diff, against this repo's standards
 *   big picture      product and platform coherence
 */

import path from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const PANEL_SCRIPT = "panel/4p.py";
const RUN_TIMEOUT_MS = 600_000;

/** Flags the launcher understands. Anything else is task text. */
const LAUNCHER_FLAGS = ["--rebrief", "--json"];

const FOLLOW_UP = (panelOutput: string): string => `The 4p panel is up. Finish the run yourself, in this order.

1. Print the panel table (role, pane, agent name, status).
2. Wait for each agent named above: \`herdr agent wait <name> --timeout 180000\`.
   If a wait fails, read that pane anyway to see whether it stalled, blocked, or errored.
3. Read each one: \`herdr agent read <name> --source recent-unwrapped --lines 200\`.
4. Present a merged view: agreements first, then the single strongest objection per
   role, then your own disposition. Synthesize it. Do not write four sections of paraphrase.

House rules for anything the user reads:
- Simplified Technical English. Sentences of 20 words maximum. Active voice.
- No em dashes.
- Do not quote pane text verbatim. Rewrite it first.
- The panes only advise. You are the only writer. Apply any patch yourself.

Panel output:

${panelOutput}`;

export default function fourP(pi: ExtensionAPI) {
	const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
	const script = path.join(packageRoot, PANEL_SCRIPT);

	pi.registerCommand("4p", {
		description: "Open the 4-pane advisory panel (AMO, tester, reviewer, big picture) in this Herdr tab",
		handler: async (args, ctx) => {
			if (process.env.HERDR_ENV !== "1") {
				ctx.ui.notify(
					"4p needs a pi session inside a Herdr pane. HERDR_ENV is not 1, so the panel cannot be created.",
					"error",
				);
				return;
			}

			// Split leading flags off, then hand the rest over as ONE argv element.
			// The launcher joins its positional args with spaces, so a single element
			// survives quoting, globbing, and shell-sensitive characters intact.
			let rest = args.trim();
			const flags: string[] = [];
			let matched = true;
			while (matched && rest) {
				matched = false;
				for (const flag of LAUNCHER_FLAGS) {
					if (rest === flag || rest.startsWith(`${flag} `)) {
						flags.push(flag);
						rest = rest.slice(flag.length).trim();
						matched = true;
						break;
					}
				}
			}
			const argv = rest ? [...flags, "--", rest] : flags;

			ctx.ui.notify(rest ? "4p: starting the panel and fanning out your task..." : "4p: starting the panel...", "info");

			const result = await pi.exec("python3", [script, ...argv], { timeout: RUN_TIMEOUT_MS });
			const output = [result.stdout, result.stderr].filter(Boolean).join("\n").trim();

			if (result.code !== 0) {
				ctx.ui.notify(`4p failed (exit ${result.code}).\n${output || "no output"}`, "error");
				return;
			}

			// The launcher prints the table; show it, then hand the loop to the model.
			ctx.ui.notify(output || "4p: panel is standing by.", "info");
			if (rest) {
				await ctx.sendUserMessage(FOLLOW_UP(output));
			}
		},
	});
}
