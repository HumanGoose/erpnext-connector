# Build the Connector in Python + FastAPI, not Node/TypeScript

Shopify's most polished SDK and GraphQL codegen tooling is JS/TypeScript-first, which would normally make Node a strong default for a Shopify-heavy integration. However, the developer is experienced in Python and unfamiliar with Node/TS, and the project's hardest learning curve is already ERPNext/Frappe and Shopify's GraphQL Admin API — adding an unfamiliar runtime on top would split that learning effort without a corresponding benefit.

We will build the Connector in Python with FastAPI (webhook receiver + API), SQLModel + SQLite (Synced Entity / Fingerprint mapping store), and APScheduler (reconciliation poll). Shopify GraphQL calls go through plain `httpx` with hand-written Pydantic models for the queries/mutations in use. ERPNext REST calls go through `frappeclient`.

## Considered Options

- **Node.js + TypeScript** — best-in-class Shopify SDK (`@shopify/shopify-api`) with built-in webhook verification and GraphQL-schema codegen, but the developer would be learning the runtime, the language, and two external systems simultaneously.

## Consequences

- No automatic type generation from Shopify's GraphQL schema; query/mutation response shapes are modeled manually as Pydantic classes (more explicit, doubles as documentation of what the Connector actually reads).
- Webhook HMAC verification and GraphQL cost-based throttling are hand-rolled rather than provided by an SDK — both are small, well-documented pieces of code.
