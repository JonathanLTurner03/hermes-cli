# Known bugs

Tracked here instead of GitHub issues since this is a small, mostly-solo repo. Move an entry out (delete it) once it's actually fixed — don't just mark it done in place.

## `hc mount disable` misreports a stop failure as a disable failure

**Where**: `hermes_cli/mount/cli.py`'s `mount_disable()` → `hermes_cli/mount/systemd.py`'s `disable_now()`.

**What happens**: `disable_now()` shells out to `systemctl disable --now <unit>` as a single combined call. `disable --now` actually does two independent things — unlink the boot-time enablement symlink, then stop the unit — but they're not atomic and the command only has one exit code. If the unlink succeeds and the stop fails (e.g. systemd cancels the stop job before it ever calls `umount`, for reasons that weren't fully diagnosed — see below), `hc` still raises `SystemdError("failed to disable <unit> (exit 1)")`, which reads as "disable didn't work" when actually the boot-time enablement *was* removed and only the live unmount failed. The unit is left in a half-torn-down state (disabled for next boot, but still actively mounted right now) with no distinction surfaced to the user.

**How it was found**: smoke-testing a throwaway bind mount (`hc-test`, source and target both under `/tmp`, which is itself tmpfs on Atlantis) — `hc mount disable hc-test` printed `Removed '.../multi-user.target.wants/tmp-hc\x2dtest\x2ddst.mount'.` (disable succeeded) followed by `Job for tmp-hc\x2dtest\x2ddst.mount canceled.` and a nonzero exit (stop failed). `journalctl -u` showed no "Unmounting..." line at all for that attempt — the stop job was thrown out before ever calling `umount`, not blocked by a busy mount point (`fuser -vm` showed no real holder, just the generic self-reference `fuser -m` prints for any active mount). Root cause of *why* the stop job got canceled wasn't pinned down — worth digging into when this gets fixed for real, since "no idea why systemd canceled it" isn't a satisfying place to stop.

**Suggested fix direction**: split `disable_now()` into an explicit `systemctl disable <unit>` followed by `systemctl stop <unit>`, so each failure can be reported distinctly (e.g. "disabled for next boot, but still live — stop failed: ..." vs. a clean full failure). Also worth deciding whether `mount_disable()` should still warn/refuse-differently when only the stop half fails, similar to how `sync --force` already has to reason about a unit being "removed from the registry but still live."
