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
No PyPI credentials or publication were used for the initial GitHub delivery.

Bootstrap empty commit author email used an unverified numeric noreply prefix in error;
the implementation commit uses the verified upstream author email.
The empty commit is retained as history rather than rewritten.

## PyPI publication follow-up

The user subsequently requested PyPI authentication and confirmed registering the
pending Trusted Publisher for `minamorl/berylx-py`, workflow `publish.yml`,
environment `pypi`. This explicitly authorizes the PyPI publication follow-up;
the original prohibition on assuming PyPI publication remains preserved in the
historical request specification.

The user then requested version upgrades to publish through CI. The
`Publish to PyPI` workflow runs when `pyproject.toml` is pushed to `main`, or is
manually dispatched from `main`. It checks the configured project version on PyPI:
HTTP 200 skips an existing version, HTTP 404 proceeds, and other HTTP or network
errors fail. New versions reuse the complete Python 3.11–3.14 CI matrix, then build
and check wheel/sdist metadata. A separate
job downloads those artifacts and obtains an OIDC token in environment `pypi`.
Only that job has `id-token: write`; no stored PyPI API token is required.
Pull requests do not publish. Publication success must be checked from the workflow result and the public PyPI project page.

Primary source read for this configuration:
[PyPI: Publishing with a Trusted Publisher](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

### PyPI release completed

Version [0.1.0 is published on PyPI](https://pypi.org/project/berylx-py/0.1.0/).
The version-triggered [publication run](https://github.com/minamorl/berylx-py/actions/runs/40872092643)
completed successfully for commit `f37c7cd526963cbdfd4270b6be40cc3e3b906c81`.
All seven jobs passed: eligibility, four Python CI versions, build, and publish.
Independent public metadata and a fresh virtual environment installation from
PyPI are recorded in `evidence/pypi-delivery.txt`, including all three README
examples executed outside the source checkout.

A [repeat dispatch of the same version](https://github.com/minamorl/berylx-py/actions/runs/40872356584)
also succeeded: eligibility recognized the existing release and skipped
validation, build, and publication without uploading again.
