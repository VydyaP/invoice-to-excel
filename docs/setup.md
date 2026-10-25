# Setup

## 1. Install (Mac or Linux)

```bash
cd invoice-to-excel
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                      # 102 tests, no API key needed
streamlit run app.py        # sample invoices work without a key
```

## 2. Measure accuracy

There are two ways to run the evaluation. Both read all 12 sample invoices with AI, score every field against `samples/answers/`, and write `docs/accuracy.md`. With `--record`, they also save the AI's answers to `demo/recorded/` for the free public demo.

### Option B: with a Claude subscription (Pro), no API key

This uses the Claude Code command-line tool, which is included with Claude Pro.

1. Install Claude Code ([quickstart](https://code.claude.com/docs/en/quickstart)), run `claude` once in any folder, and sign in with your Claude account. Type `/exit` to leave.
2. Make sure no API key is set in this terminal, so your Pro login is used: `unset ANTHROPIC_API_KEY`.
3. In the project folder, with the virtual environment active:

   ```bash
   python scripts/evaluate.py --provider claude-code --record
   ```

   It prints `[1/12] reading ...` for each invoice (about 10 to 30 seconds each) and then a summary.

Each invoice is copied into an empty temporary folder and Claude Code is only allowed to use its Read tool there. The run counts towards your Pro usage limits like any other Claude Code session. If you hit a limit, wait for it to reset and run the same command again.

`docs/accuracy.md` will say the answers came through Claude Code and which model read them. The web app's "Read your own invoices" tab still uses the API (option A). To pick the Claude Code model: `--model sonnet` or `--model haiku`.

### Option A: with an Anthropic API key

This needs your own Anthropic API key (API credit is billed separately from Claude Pro). **Never paste the key into a chat, an issue, a commit or the web page.**

1. Sign in to the [Claude Console](https://console.anthropic.com), add a little credit, and set a monthly spend limit in the Console's limits settings. One full evaluation run is 12 API calls.
2. Create a key under **API keys**.
3. In the terminal, in the project folder with the virtual environment active:

   ```bash
   export ANTHROPIC_API_KEY="paste-your-key-here"   # only lasts for this terminal window
   python scripts/evaluate.py --record
   ```

   It prints a short summary and writes:
   - `docs/accuracy.md`: fields read correctly, problems caught, false alarms, time and estimated cost, plus every field the AI got wrong
   - `demo/recorded/*.json`: the AI's real answers, which the public demo replays for free

4. (Both options) Check `git status`: only `docs/accuracy.md` and `demo/recorded/` should have changed (the samples are fictional, so these are safe to publish). Commit and push.

To try a different model: `INVOICE_MODEL=<model id> python scripts/evaluate.py`. To re-score saved answers without calling the API: `python scripts/evaluate.py --provider recorded`.

If one invoice keeps failing, `python scripts/evaluate.py --only inv05_malnad_photo` runs just that one.

## 3. Read your own invoices locally

Either keep the `export` from step 2, or save the key in a file that git ignores:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # then edit and paste the key
streamlit run app.py
```

Open **Read your own invoices**, upload up to 25 PDFs or photos, and press **Read invoices**.

## 4. Public demo (Streamlit Community Cloud)

1. Push the repo to GitHub (after step 2, so the demo shows real AI answers).
2. At [share.streamlit.io](https://share.streamlit.io) choose **Create app**, pick the repo, branch `main`, main file `app.py`.
3. **Do not add your API key to the public app's secrets.** Anyone on the internet could then spend your credit. Without a key, the public page runs the sample demo and explains that reading new invoices needs a key.

For a client, run it on their machine or a private deployment with their own key and spend limit.
