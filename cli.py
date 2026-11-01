#!/usr/bin/env python3
"""Interactive CLI for the text-tagger prototype.

Usage:
    python cli.py --mock          session over a generated mock job
    python cli.py job.json        session over a job file
    cat job.json | python cli.py  session over a piped JSON job

Commands:
    <N>      select underline #N
    n / p    cycle next / previous candidate
    y        apply the currently selected candidate
    t <text> retype the whole segment (custom replacement or word split)
    d        false positive: drop the underline, keep the original text
    a        approve: print the final text and exit
    q        abort without approving
"""

import json
import sys

from mock_data import generate_mock
from tagger import approve, apply_replacement, drop, load_job, render, replace_segment

BOLD = "\033[1m"
UNDER = "\033[4m"
DIM = "\033[2m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"

HELP = ("commands: <N> select | n/p cycle candidates | y apply | t <text> retype\n"
        "          d drop (false positive) | a approve | q abort")


class Session:
    def __init__(self, job):
        self.job = job
        self.sel = None
        self.cand = 0
        self.done = False

    def _selected(self):
        if self.sel is None:
            print("select an underline first (<N>)")
            return None
        if self.sel >= len(self.job["underlines"]):
            print("selection vanished (segment already resolved), pick another")
            self.sel = None
            return None
        return self.job["underlines"][self.sel]

    def select(self, num):
        if not 1 <= num <= len(self.job["underlines"]):
            print(f"no underline #{num}")
            return
        self.sel = num - 1
        self.cand = 0

    def cycle(self, step):
        u = self._selected()
        if u is None:
            return
        if not u["candidates"]:
            print("this span has no candidates, use t <text> to retype it")
            return
        self.cand = (self.cand + step) % len(u["candidates"])
        print(f"candidate: {u['candidates'][self.cand]}")

    def apply(self):
        u = self._selected()
        if u is None:
            return
        if not u["candidates"]:
            print("this span has no candidates, use t <text> to retype it")
            return
        chosen = u["candidates"][self.cand]
        apply_replacement(self.job, self.sel, chosen)
        print(f"replaced with {chosen!r}")
        self.sel = None

    def retype(self, new_text):
        u = self._selected()
        if u is None:
            return
        segment = self.job["text"][u["left_pos"]:u["right_pos"]]
        if not new_text:
            new_text = input(f"{RED}retype{RESET} text for {segment!r} (empty = keep as-is) > ").strip()
        if not new_text:
            return
        replace_segment(self.job, self.sel, new_text)
        print(f"segment {segment!r} retyped to {new_text!r}")
        self.sel = None

    def drop_underline(self):
        u = self._selected()
        if u is None:
            return
        segment = self.job["text"][u["left_pos"]:u["right_pos"]]
        drop(self.job, self.sel)
        print(f"dropped tag on {segment!r} (false positive)")
        self.sel = None

    def approve(self):
        text = approve(self.job)
        print("\n--- FINAL TEXT ---")
        print(text)
        self.done = True

    def handle(self, line):
        parts = line.split(None, 1)
        head, arg = parts[0], parts[1].strip() if len(parts) > 1 else ""
        if head == "n":
            self.cycle(+1)
        elif head == "p":
            self.cycle(-1)
        elif head == "y":
            self.apply()
        elif head == "t":
            self.retype(arg)
        elif head == "d":
            self.drop_underline()
        elif head == "a":
            self.approve()
        elif head == "q":
            print("aborted, nothing saved")
            self.done = True
        else:
            try:
                self.select(int(head))
            except ValueError:
                print(f"unknown command: {line!r}\n{HELP}")
                return

    def show(self):
        job = self.job
        print()
        for piece, idx in render(job):
            if idx is None:
                sys.stdout.write(piece)
            else:
                sys.stdout.write(f"{UNDER}{BOLD}{piece}{RESET}{DIM}[{idx + 1}]{RESET}")
        print()
        if not job["underlines"]:
            print(f"{DIM}no underlined segments left{RESET}")
        for i, u in enumerate(job["underlines"]):
            segment = job["text"][u["left_pos"]:u["right_pos"]]
            mark = f"{GREEN}>{RESET}" if i == self.sel else " "
            if u["candidates"]:
                if i == self.sel:
                    listing = " / ".join(
                        f"{YELLOW}{c}{RESET}" if j == self.cand else c
                        for j, c in enumerate(u["candidates"])
                    )
                    detail = f"candidates: {listing}"
                else:
                    detail = f"{len(u['candidates'])} candidates"
            else:
                detail = "no candidates"
            print(f"{mark} {i + 1}: {BOLD}{segment}{RESET}  {DIM}{u['type']}{RESET}  {detail}")
        if self.sel is not None:
            u = job["underlines"][self.sel]
            if u["candidates"]:
                print(f"{DIM}selected candidate: {u['candidates'][self.cand]!r} (y to apply){RESET}")


def main():
    args = [a for a in sys.argv[1:] if a != "--mock"]
    if "--mock" in sys.argv[1:]:
        raw = generate_mock()
    elif args:
        with open(args[0], encoding="utf-8") as fh:
            raw = json.load(fh)
    elif not sys.stdin.isatty():
        raw = json.load(sys.stdin)
    else:
        print(__doc__)
        return 2
    session = Session(load_job(raw))
    print("text-tagger prototype session")
    print(HELP)
    while not session.done:
        session.show()
        try:
            line = input("tagger> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if line:
            session.handle(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
