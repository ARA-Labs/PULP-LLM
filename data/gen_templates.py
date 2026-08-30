"""
Use claude -p (Opus, cost-guarded flags) to write 22+ paraphrase templates per fact type for
DAPT augmentation v3 — the "diversity > repetition" fix. Templates use named {placeholders};
about a third must be REVERSED forms (value first, name second) to dodge the reversal curse.

Output: templates_v3.json  {type: [template, ...]}
Falls back to built-in templates for any type whose LLM output fails validation.
"""
import json
import re

import subprocess
import time


def call_claude(system: str, prompt: str, mcp_cfg: str, timeout=300, retries=4) -> dict:
    """Headless claude -p call with cost-guard flags (strips dynamic context: ~$0.03/call)."""
    cmd = ["claude", "-p", "--model", "claude-opus-5", "--tools", "", "--no-session-persistence",
           "--exclude-dynamic-system-prompt-sections", "--disable-slash-commands",
           "--strict-mcp-config", "--mcp-config", mcp_cfg, "--system-prompt", system,
           "--output-format", "json"]
    err = ""
    for attempt in range(retries):
        try:
            r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0 and r.stdout.strip():
                d = json.loads(r.stdout)
                if not d.get("is_error"):
                    return d
                err = str(d.get("result"))[:200]
            else:
                err = f"rc={r.returncode} {r.stderr[-200:]}"
        except Exception as e:
            err = str(e)[:200]
        time.sleep(min(60, 5 * 2 ** attempt))
    return {"is_error": True, "result": "", "error": err}

TYPES = {
    "offset": (["ip", "reg", "a"],
               "a hardware register byte offset: register {reg} of block {ip} is at offset {a} "
               "(a hex value like 0x14)"),
    "base": (["name", "a"],
             "an SoC memory-map base address: the macro/region {name} has base address {a}"),
    "size": (["name", "a"],
             "an SoC memory-map region size: region {name} has size {a} bytes (hex)"),
    "bits": (["ip", "reg", "field", "a"],
             "a register field bit position: field {field} of register {reg} in block {ip} "
             "occupies bit(s) {a} (like 7:0 or 3)"),
    "swaccess": (["ip", "reg", "field", "a"],
                 "a register field software access type: field {field} of register {reg} in "
                 "block {ip} has swaccess {a} (like rw, ro, rw1c)"),
    "desc": (["ip", "reg", "a"],
             "a register's documented purpose: register {reg} of block {ip} is documented as: {a}"),
    "bender": (["dep", "a"],
               "a dependency pin: the Carfield Bender.yml manifest pins dependency {dep} at version {a}"),
    "inst": (["inst", "mod"],
             "an RTL instantiation: in carfield.sv the instance {inst} instantiates module {mod}"),
    "issue": (["repo", "num", "title"],
              "a GitHub issue: pulp-platform/{repo} issue #{num} is titled {title}"),
    "driver": (["repo", "file", "fn", "macro"],
               "a driver correspondence: C function {fn} in file {file} of repo {repo} uses the "
               "register offset macro {macro}"),
}

FALLBACK = {t: [] for t in TYPES}

SYS = ("You write short reusable English text templates for technical training data. "
       "Reply with ONLY a JSON array of strings, no markdown fences, no commentary.")

PROMPT = """Write 24 different one-or-two-sentence English templates that each state {what}.
Context: PULP Carfield/Cheshire hardware platform (ETH Zurich), chip RTL / SoC documentation.

Rules:
- Each template MUST contain every placeholder of: {ph} (written exactly with braces).
- Vary the register/genre widely: datasheet prose, table row, C comment, code snippet, commit
  message, forum answer, tutorial, quiz question with its answer, changelog line, spec bullet.
- At least 8 templates must be REVERSED: the value/answer appears BEFORE the entity name
  (e.g. "Offset {a} in {ip} belongs to {reg}." style).
- One line per template, no numbering. Plain JSON array of 24 strings only."""


def valid(tpl: str, phs) -> bool:
    if not (10 < len(tpl) < 400):
        return False
    return all("{%s}" % p in tpl for p in phs)


def main():
    out = {}
    for t, (phs, what) in TYPES.items():
        prompt = PROMPT.replace("{what}", what).replace("{ph}", ", ".join("{%s}" % p for p in phs))
        d = call_claude(SYS, prompt, "empty_mcp.json")
        tpls = []
        try:
            txt = d.get("result", "")
            txt = re.sub(r"^```\w*\n?|```$", "", txt.strip(), flags=re.M)
            arr = json.loads(txt)
            tpls = [x for x in arr if isinstance(x, str) and valid(x, phs)]
        except Exception as e:
            print(t, "parse fail:", e)
        print(f"{t}: {len(tpls)} valid  (cost ${d.get('total_cost_usd', 0):.3f})")
        out[t] = tpls
    json.dump(out, open("templates_v3.json", "w"), indent=1)
    print("wrote templates_v3.json")


if __name__ == "__main__":
    main()
