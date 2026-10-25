# Setup

## 1. Install (Mac or Linux)

```bash
cd invoice-to-excel
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                      # 90 tests, no API key needed
streamlit run app.py        # sample invoices work without a key
```

## 2. Measure accuracy

This needs your own Anthropic API key. **Never paste the key into a chat, an issue, a commit or the web page.**

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

4. Check `git status`: only `docs/accuracy.md` and `demo/recorded/` should have changed (the samples are fictional, so these are safe to publish). Commit and push.

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
