# Novelty budget and memory indexes

If a run stops with `Novelty budget exhausted`, the run would add more new files or
public names than the budget allows: raise the budget in `ract.yaml`, or pass
`--allow-novelty-overrun` for that run.

`ract memory init` builds three indexes. The semantic one needs the embedding
model's files on this machine: set `RACT_EMBED_MODEL_ROOT` to the folder that
holds them, or `RACT_EMBED_ONLINE=1` to let RACT download them. Without either,
the other two indexes still build and the command still succeeds.
