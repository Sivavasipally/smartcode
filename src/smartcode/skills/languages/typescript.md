### TypeScript skill
- `strict` mindset: no `any` unless unavoidable; prefer `unknown` + narrowing.
- Use `interface` for object shapes, `type` for unions/utilities; export explicit types.
- Prefer `const`, arrow functions for callbacks, async/await over raw promises.
- Narrow errors: `catch (err) { if (err instanceof Error) ... }`.
- ES modules (`import`/`export`), named exports over default exports.
