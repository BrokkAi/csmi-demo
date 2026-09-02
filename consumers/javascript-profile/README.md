# JavaScript/Node profile consumer

This dependency-free Python consumer independently implements the exact profile
subset used by `scenarios/node-builtin-alias`. It compares full artifact and
structural symbol identity, validates required profile declaration and module
binding consistency, and never treats source spellings or export names alone as
identity.

Run:

```sh
python3 -m unittest discover -s consumers/javascript-profile -p 'test_*.py' -v
python3 consumers/javascript-profile/consumer.py --pack scenarios/node-builtin-alias/pack.json --cases scenarios/node-builtin-alias/cases.json --mode off
python3 consumers/javascript-profile/consumer.py --pack scenarios/node-builtin-alias/pack.json --cases scenarios/node-builtin-alias/cases.json --mode on
```

Use `--archive node-v22.11.0-linux-x64.tar.xz` to verify independently
downloaded official distribution bytes against the pinned digest.
