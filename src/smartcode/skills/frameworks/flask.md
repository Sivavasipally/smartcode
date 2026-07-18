### Flask skill
- Blueprints per resource; application-factory pattern (`create_app`).
- Validate input explicitly (pydantic/marshmallow); return (json, status) tuples.
- Errors via `@app.errorhandler` returning JSON, not HTML.
- Config from environment; never hardcode secrets.
