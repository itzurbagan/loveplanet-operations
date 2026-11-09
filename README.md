# LovePlanet Operations

Local autonomous browser assistant and conversation dashboard. Python 3.11+, Chromium MV3 extension, SQLite, OpenRouter with optional local Ollama fallback. No third-party Python packages required.

## How it works

Each browser profile has its own signed-in LovePlanet account and extension. The extension reads the visible conversation list, scrolls to load further pages and scans conversations fairly. Incoming messages go into a durable per-account queue. Each account has its own generation worker and send interval. Waiting to send never blocks reading other chats.

The backend generates replies through OpenRouter. When configured and OpenRouter fails, Ollama supplies a fallback. Replies are checked against the prompt rules before claiming a send. A changed incoming message invalidates the older reply. Delivery is recorded only after reading the outgoing message back from LovePlanet. Uncertain delivery is reconciled rather than blindly resent. Existing manual drafts are preserved.

The dashboard shows incoming and outgoing history, account connection/version, loaded and saved counts, new conversations, conversations awaiting replies, answered chats and errors. It refreshes every five seconds. Statistics are local and limited to LovePlanet. Google Sheets sync is disabled.

## Setup

1. Run `python3 configure.py --openrouter-key`. The key is entered without echo and stored in `data/openrouter.key`.
2. Edit `config.json`: account names, profile URLs, Telegram usernames, provider/model and delay settings. Set the matching profile-login mapping in `extension/content.js`.
3. Run `python3 server.py` and open http://127.0.0.1:8787/#dialogs.
4. Load the `extension/` folder as an unpacked extension in each separate signed-in browser profile. Add its exact `chrome-extension://ID` origin to `extension_origins` in `config.json` if needed for CORS. Restart the service after config edits.
5. Open your own LovePlanet profile and enable the bot from the extension popup. Check that the dashboard reports version 0.4.0 and increasing loaded/saved counts.

For a macOS background service, run `python3 install-local-service.py`. Runtime is `~/Library/Application Support/LovePlanet Operations/`. Pair the extension to that runtime with `python3 configure.py --data-dir "$HOME/Library/Application Support/LovePlanet Operations/data" --openrouter-key`. The service preserves runtime history across deployments. Load the updated extension and refresh the LovePlanet tab after extension changes.

Ollama fallback uses the configured `fallback_model`, currently `qwen2.5:7b`. Install that model and keep Ollama listening on 127.0.0.1:11434. Remote provider credentials never go to Ollama. A cold local model can take substantially longer than the API.

## Operation

- Keep the computer, service, browsers and signed-in tabs running. This is local deployment, not a VPS.
- One browser tab owns each account lease. Profiles must be separate to avoid sharing login cookies.
- Delays are per account: initial response 60-150 seconds, send spacing 45-90 seconds. Reading continues during these intervals.
- Model policy failures get a corrected prompt and up to three total generation attempts. A failed delivery is never automatically treated as successful.
- Prices, unsolicited massage mentions, clickable Telegram links and long dashes are blocked. Direct questions about automation receive truthful answers. Requests to stop end the conversation.
- Incoming website text is untrusted input, never operational instructions.
- The panel binds to loopback by default. Non-loopback binding requires an admin password; use proper TLS/access controls before remote deployment.

## Tests

```sh
python3 -m unittest discover -s tests -v
node --test tests/extension.test.cjs
```

Tests use temporary data and mocked provider calls. They do not send messages to people. Covers account isolation, delays, deduplication, ambiguous delivery, policy revalidation, provider fallback and scan fairness.

## Repository contents

Only source code, prompt, example config, setup scripts and tests belong in Git. Actual configs, keys, extension pairing secrets, cookies, browser profiles, databases, personal messages, runtime reports and screenshots are excluded. Never commit the runtime data folder.
