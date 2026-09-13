# LLM Picker frontend

React, TypeScript, and D3 frontend built with Vite.

## Quick Start

Prerequisites: Make sure you have `node.js` and `npm` installed.

```bash
# Install dependencies
npm install
# Start the development server
npm run dev
# Create the production build
npm run build
```

The development server runs on `http://localhost:5173` by default. The Django
backend permits local Vite ports while `DEBUG` is enabled.

## Tests

```bash
# Run Oxlint
npm run lint
# Run TypeScript type checking
npm run typecheck
# Run unit tests
npm run test
```

## API Client

The typed API surface is exported from `src/api`. It uses
`http://127.0.0.1:8000/api/v1/leaderboard/` by default. Override the base URL in
a local `.env` file when needed:

```dotenv
VITE_API_BASE_URL=https://example.com/api/v1/leaderboard/
```
