### Go skill
- Follow effective-go: short receiver names, error as last return value.
- Always check errors: `if err != nil { return ..., fmt.Errorf("context: %w", err) }`.
- Accept interfaces, return concrete types. Keep packages small and cohesive.
- Use gofmt formatting (tabs); exported identifiers get doc comments.
