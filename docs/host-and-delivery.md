# Execution provenance and delivery state

Actual implementation host: vultr fallback (Linux), workspace `/home/minamorl/repos`.
Core dedicated worktree: `/home/minamorl/repos/.worktrees/berylx-py-port`, branch `port`.
Timeline dedicated worktree: `/home/minamorl/repos/.worktrees/berylx-py-timeline`.
The base new repository is `/home/minamorl/repos/berylx-py`; no existing Python
repository was overwritten. The initial empty commit only enabled worktree creation.

The parent verified the MacBook preference before implementation. Tailscale reported
`macbook-pro.tail7cac55.ts.net` Online=false; `ssh -o BatchMode=yes -o ConnectTimeout=5
minamorl@100.108.246.90 hostname` exited 255 with timeout. Host alias resolution also
failed and Paseo had no registered remote hosts. Tau remained excluded. This session
was already a Paseo Codex session; development continued on the available vultr host.

Tracked contract repository: `/home/minamorl/repos/cc`, revision
`f88fe230996d9ffa0ddc3cd6f8ee55860ff350b5`. Read its Codex AGENTS.md, canonical
`.claude/skills/spec-lane/SKILL.md`, spec-system boot contract and Ruby-target berylx
pin. Python target was uncovered: declared code-first and independently lifted the
requested specification. SAT consistency output is in `evidence/spec-sat.txt`.

Independent scout rounds used tracked runtime metadata: Codex gpt-5.6-luna safe mode
on the TS checkout, and gpt-5.6-terra safe mode on the Python checkout. They checked
different contracts and emphasized result namespace separation, Validation bind vs
accumulating ap, and partial-state retention. Scouts are review, not execution proof;
initial package absence was the expected tests-first state, not an implementation bug.

## Delivery status: published

Public repository: https://github.com/minamorl/berylx-py .

The initial create attempt failed with exit 4 because the current process user,
`paseo-a`, had no GitHub CLI authentication. After the user completed GitHub device
login as `minamorl`, repository creation and `git push -u origin main` both exited 0.
The implementation commit is `45a1bc812f036abe4254073e0b42e995c780667a`.
An unauthenticated GitHub API request confirmed `private: false` and `visibility: public`.
Historical failure and successful delivery evidence are in `evidence/delivery.txt`.
No PyPI credentials or publication have been used.

Bootstrap empty commit author email used an unverified numeric noreply prefix in error;
the implementation commit uses the verified upstream author email.
The empty commit is retained as history rather than rewritten.
