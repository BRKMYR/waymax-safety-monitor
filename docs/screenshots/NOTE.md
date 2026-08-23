# Screenshots

This directory is populated by the headless dashboard runner. It is intentionally empty in-repo (no fabricated stills are checked in).

## Regenerating

From the repo root, with the package installed (`pip install -e ".[dev]"`):

```bash
# All bundled scenarios, one PNG per timestep.
for scenario in intersection_conflict highway_merge pedestrian_crossing hard_brake stalled_ego; do
  safety-monitor \
    --scenario "$scenario" \
    --headless \
    --frames-out "docs/screenshots/$scenario" \
    --events-out "docs/screenshots/$scenario/events.json" \
    --frame-stride 1
done
```

Each run emits:

- `frame_000.png` .. `frame_090.png` (91 frames at 10 Hz).
- `events.json` with every fired trigger, sorted by `(timestep, agent_id, kind)`.

Set `--frame-stride 10` to keep only every tenth frame for compact demo GIFs.

## Why this file exists

The repo policy is to keep example outputs reproducible and version-controlled sources rather than committing generated binaries. If you want the images live in the repo, run the commands above and commit the resulting directories. The CI pipeline in `.github/workflows/ci.yml` runs the same headless path to gate every PR on the `hard_brake` RED trigger firing at `(agent_id=1, timestep=31)`.
