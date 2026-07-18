### Express skill
- Router per resource; middleware for auth/validation/logging.
- Central error handler (`(err, req, res, next)`); async handlers wrapped to forward rejections.
- Validate request bodies (zod/joi) before handlers touch them.
- Never send stack traces to clients; consistent JSON error envelope.
