# RepoMind AI

Ask questions about a specific public GitHub commit and follow the answer's citations to the original source.

## Start on Windows

1. Open Docker Desktop and wait for the engine to run.
2. In the project folder, double-click **Start RepoMind.cmd**. It generates a local signing secret for a fresh installation, builds the application and opens the dashboard when both databases respond. Existing .env settings and database volumes are reused.
3. For AI features, obtain a Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey). Double-click **Configure Google.cmd**, paste the key at the hidden prompt, then run **Start RepoMind.cmd** again. The key stays in the project-root .env. Keep that file private, including in any OneDrive sharing settings.
4. Open http://localhost:5173/dashboard. Register or sign in. Submit a canonical public URL such as https://github.com/pypa/sampleproject. Source retrieval and AI indexing show separate statuses. Choose **Index source** for older snapshots or **Retry indexing** after correcting a failure.
5. Choose **Open chat**, enter a question, and click a file citation to open the indexed commit and line range. Reopening the repository restores saved conversations. Delete chat removes one conversation. Delete on the dashboard removes that repository's source, vectors and messages.

Service checks are at http://localhost:5173/setup. Stop with `docker compose down` in the project folder. Named volumes persist. Source ingestion, account access and service checks work independently of Google credentials.

## Architecture and data

React/Vite, Tailwind and Axios use same-origin FastAPI endpoints through Nginx. MongoDB stores bcrypt password hashes, normalized unique emails, revocable sessions, repository snapshots, persistent job states, conversations and message turns. Registration uses 12+ characters and enforces bcrypt's 72-byte limit. A one-hour signed JWT is held in a scoped HttpOnly, SameSite=Strict cookie. Mutations require the custom CSRF header. Every repository and conversation operation derives ownership from the session.

GitHub REST resolves the default branch once. The worker reads the commit's immutable tree and blobs, checks blob hashes, and rejects truncated trees. Retained UTF-8 source stays in one bounded MongoDB document. It is never executed or written to source paths on disk. Path and content checks skip hidden files, dependency/build directories, symlinks, binaries, oversized files, and detected credentials. A matching file is excluded entirely, preserving original line numbers in retained files. Detection is heuristic and cannot guarantee every secret is recognized.

A single indexing worker claims MongoDB jobs. LangChain RecursiveCharacterTextSplitter produces lossless partitions. Overlap is sliced from original character offsets, and line numbers come from original newline positions. Before embedding, the worker rechecks stored files against the current filters. Qdrant exclusively stores chunk vectors and their source evidence. IDs are deterministic UUIDs. The collection uses cosine similarity and a named vector corresponding to the embedding model. Retrieval requires the repository and commit filters.

Google receives filtered source passages for document embeddings, questions for query embeddings, and up to 16,000 characters of retrieved evidence plus limited history for answers. Three previous turns contribute at most 400 question characters and 800 answer characters each. Instructions are sent separately from untrusted evidence. The server validates returned evidence IDs and builds GitHub URLs from stored metadata. An insufficient-evidence response has no citations. Valid links identify genuine retrieved lines; they do not guarantee the model's interpretation is correct.

A successful question and answer are inserted as one MongoDB turn. Failed provider requests do not create successful turns. Markdown is rendered without raw HTML, model-provided links or remote images. Only server-built citation links are interactive.

## Configuration

Compose reads **.env beside compose.yaml**. The root .env.example lists the variables. backend/.env.example documents standalone backend environment names. The frontend requires no credentials.

| Setting | Default or use |
| --- | --- |
| GOOGLE_API_KEY | Required for live AI. Configure Google.cmd writes it locally without echoing. |
| GOOGLE_CHAT_MODEL | gemini-3.5-flash-lite. Select a Gemini model available to your key that supports generateContent and JSON output. |
| GOOGLE_EMBED_MODEL | gemini-embedding-001. The adapter uses its native RETRIEVAL_DOCUMENT and RETRIEVAL_QUERY task types. Other task conventions require an adapter change. |
| VECTOR_DIM | 768. Document and query requests specify the same dimension. Restore the original configuration if Qdrant reports an incompatible collection. |
| EMBED_BATCH / RETRIEVAL_TOP_K | 12 chunks per batch / 5 retrieved passages. |
| CHUNK_SIZE / CHUNK_OVERLAP / MAX_CHUNKS | 1400 / 160 characters; 1500 chunks per repository. |
| JWT_SECRET / COOKIE_SECURE | Random signing key of at least 32 bytes. Local HTTP uses false. Production HTTPS uses true. |
| GITHUB_TOKEN | Optional public-repository token for GitHub rate limits. |
| REPO_REPO_KIB / REPO_FILES | 50000 KiB GitHub-reported size; 300 eligible files. |
| REPO_FILE_BYTES / REPO_DOWNLOAD_BYTES / REPO_STORED_BYTES | 200000 per file; 12000000 cumulative response bytes; 4000000 retained source bytes. |
| REPO_SECONDS | 120 seconds for source retrieval. |

Google model availability depends on your key and region. Check the model in AI Studio or the authenticated Models API and use its bare model ID. The backend checks supported methods and embedding lengths at runtime. Changing vector spaces requires a separate migration; changing the chat model requires only a restart. See [models API](https://ai.google.dev/api/models), [Google embeddings](https://ai.google.dev/gemini-api/docs/embeddings), and [Gemini models](https://ai.google.dev/gemini-api/docs/models).

## Limits, recovery and troubleshooting

Run one backend process and one Compose replica. The job and conversation coordination assumes this topology. Each account can keep 50 repositories, 50 conversations per repository and 100 turns per conversation. Retrieval queues at most 20 waiting jobs. Indexing is serial, with a ten-minute deadline checked between batches. Questions are limited to 2000 characters, three concurrent answers globally and twelve question attempts per account per minute. Submissions and index retries each allow four per account per minute. Rate counters reset on backend restart.

Pending AI jobs resume. Interrupted active indexing becomes failed and can be retried against the same snapshot. Retries clear previous points before rewriting; incomplete indexes are inaccessible to chat. Interrupted source retrieval can be deleted and resubmitted. Deletion marks the record before removing vectors and dependent MongoDB data. If deletion was interrupted, the worker revisits marked repositories. During a provider outage, retry deletion after the provider recovers.

- **Set GOOGLE_API_KEY**: use the hidden-input launcher and rebuild. Then choose Retry indexing.
- **Provider rejected request**: check the selected model, its supported methods, API project access and dimensions. A quota or temporary outage uses bounded retries. Keep existing vectors and restore compatible settings before retrying.
- **Docker engine access denied**: launch Docker Desktop and run Start RepoMind.cmd from your Windows account. A sandboxed terminal can lack access even while Docker is running.
- **Sign-in or service trouble**: open /setup, check Docker Desktop container status and verify the root .env still has the original JWT_SECRET. Keep the existing database volumes.

## Tests and development

From backend in a Python 3.12 virtual environment, run `python -m pip install -r requirements-test.txt` and `python -m pytest tests`. The test suite isolates MongoDB and external providers. The Linux Docker build uses requirements.lock.

From frontend, run `npm ci` and `npm run build`. For local UI development run `npm run dev` alongside FastAPI on port 8000. Set backend environment variables in the process and supply reachable local MongoDB and Qdrant services. Vite proxies /api to FastAPI.

For the browser journey, set REPOMIND_TEST_URL to an isolated running test stack, then run `npm test` from frontend. It uses Edge via Playwright; BROWSER_CHANNEL can select another installed Chromium channel. It creates a temporary test account, submits pypa/sampleproject, indexes it, asks a question, verifies a pinned citation, reloads, signs out/in and deletes the chat and repository. The test account remains in that test database. A real Google configuration consumes API quota.

For Compose validation run `docker compose config --quiet`. Keep the default deployment bound to loopback. For a production deployment terminate HTTPS at a trusted proxy, set COOKIE_SECURE=true, restrict database networking, protect secrets and configure persistent backups. Keep the single backend process until distributed job coordination is implemented.

