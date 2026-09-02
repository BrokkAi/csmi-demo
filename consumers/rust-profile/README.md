# Rust profile consumer

This is a small, dependency-free independent consumer for `csmi.rust` 0.1.0.
It consumes the exact valid Rust profile fixture from the CSMI specification and
projects only resolver-shaped structural identities and profile facts; it does
not use Bifrost APIs, local analyzer handles as identity, source text, display
names, or mangled names.

The projection demonstrates:

- a Cargo-resolved `lib:acme_codec` crate root, keeping package and crate names
  distinct;
- an inherent associated generic function and its positional type parameter;
- a trait implementation with an exact structured implementation key and
  provided-to-trait associated-item mapping;
- a portable procedural-macro generated item with input/output evidence; and
- an explicit exact native boundary scoped to compiler, target, and artifact
  bytes.

Run the consumer and tests from the repository root:

```sh
python3 consumers/rust-profile/verify.py
python3 -m unittest discover -s consumers/rust-profile -p 'test_*.py' -v
```

The tests mutate the fixture to demonstrate fail-closed behavior for an
unsupported required profile, missing configuration evidence, a package-name
heuristic, and name-only trait correspondence. A successful result means only
that the exact fixture and supported profile subset were interpreted; it is
not a claim that a Rust compiler or ABI has been standardized.
