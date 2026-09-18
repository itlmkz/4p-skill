/**
 * Harness: load the extension with a mock `pi` and check what it does.
 * Run: npm test   (or: node --experimental-strip-types tests/extension.test.mjs)
 */

import { fileURLToPath } from "node:url";

const MODULE = fileURLToPath(new URL("../extensions/four-p.ts", import.meta.url));
const { default: fourP } = await import(MODULE);

let failures = 0;
const check = (label, got, want) => {
	const g = JSON.stringify(got);
	const w = JSON.stringify(want);
	const ok = g === w;
	if (!ok) failures++;
	console.log(`${ok ? "PASS" : "FAIL"}  ${label}`);
	if (!ok) console.log(`        got  ${g}\n        want ${w}`);
};

async function run(args, herdrEnv, expectedCode = 0) {
	const calls = [];
	const notices = [];
	const userMessages = [];
	const pi = {
		registerCommand: (name, opts) => calls.push({ kind: "register", name, opts }),
		exec: async (cmd, argv, opts) => {
			calls.push({ kind: "exec", cmd, argv, opts });
			return { stdout: "PANEL TABLE", stderr: "", code: expectedCode, killed: false };
		},
	};
	fourP(pi);
	const { name, opts } = calls[0];
	const prev = process.env.HERDR_ENV;
	if (herdrEnv === undefined) delete process.env.HERDR_ENV;
	else process.env.HERDR_ENV = herdrEnv;
	try {
		await opts.handler(args, {
			ui: { notify: (msg, level) => notices.push({ msg, level }) },
			sendUserMessage: async (m) => userMessages.push(m),
		});
	} finally {
		if (prev === undefined) delete process.env.HERDR_ENV;
		else process.env.HERDR_ENV = prev;
	}
	return { name, calls, notices, userMessages };
}

// 1. the command registers under the right name
{
	const { name } = await run("", "1");
	check("registers command '4p'", name, "4p");
}

// 2. refuses to run outside Herdr, and does not execute anything
{
	const { calls, notices } = await run("", undefined);
	check("outside Herdr: no exec", calls.filter((c) => c.kind === "exec").length, 0);
	check("outside Herdr: notifies error", notices[0]?.level, "error");
}

// 3. argv construction. argv[0] is the resolved launcher path, so compare the tail.
const argvOf = async (args) => {
	const { calls } = await run(args, "1");
	return calls.find((c) => c.kind === "exec")?.argv;
};

check(
	"script path resolves from the package, not a home directory",
	(await argvOf(""))?.[0],
	fileURLToPath(new URL("../panel/4p.py", import.meta.url)),
);

const tailOf = async (args) => (await argvOf(args))?.slice(1);

check("bare /4p -> no flags, no task", await tailOf(""), []);
check("/4p <task> -> single task element", await tailOf("do the thing"), ["--", "do the thing"]);
check("/4p --rebrief <task>", await tailOf("--rebrief do the thing"), ["--rebrief", "--", "do the thing"]);
check("/4p --rebrief alone", await tailOf("--rebrief"), ["--rebrief"]);
check(
	"quotes and dollars survive verbatim",
	await tailOf('review "the thing" and $HOME'),
	["--", 'review "the thing" and $HOME'],
);
check("a task starting with a dash", await tailOf("--rebrief -weird task"), ["--rebrief", "--", "-weird task"]);

// 4. a task triggers the follow-up so the coordinator finishes the run
{
	const withTask = await run("do the thing", "1");
	const without = await run("", "1");
	check("task -> follow-up sent", withTask.userMessages.length, 1);
	check("no task -> no follow-up", without.userMessages.length, 0);
	check("follow-up carries the panel table", withTask.userMessages[0].includes("PANEL TABLE"), true);
	check("follow-up states the write rule", withTask.userMessages[0].includes("only writer"), true);
}

// 5. a failing launcher surfaces its output and does not send a follow-up
{
	const { notices, userMessages } = await run("do the thing", "1", 1);
	check("failure -> error notify", notices.some((n) => n.level === "error"), true);
	check("failure -> no follow-up", userMessages.length, 0);
}

console.log(failures === 0 ? "\nall checks passed" : `\n${failures} check(s) failed`);
process.exit(failures === 0 ? 0 : 1);
