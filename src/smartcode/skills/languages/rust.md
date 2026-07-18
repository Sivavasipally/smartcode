### Rust skill
- Return `Result<T, E>`; use `?` propagation, `thiserror`/`anyhow` idioms where fitting.
- Prefer borrowing over cloning; avoid `unwrap()`/`expect()` outside tests.
- Derive common traits (`Debug`, `Clone`, `PartialEq`) on data types.
- Use iterators/combinators over index loops; `clippy`-clean style.
