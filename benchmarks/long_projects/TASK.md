# Model discovery across client and CLI

Add `--model auto` as the CLI default. In `BonsaiLLM`, resolve `auto` lazily from the local server's `/v1/models` response before sending a chat or tool request, cache the ID for later requests, and preserve explicit model names. Raise a useful error if the server reports no models. Do not modify existing or acceptance tests. Run the full test suite.
