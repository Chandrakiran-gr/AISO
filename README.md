# Integrated AI — AISO Platform

**AI Search Optimization (AISO)** research and service platform. Measures how often client businesses appear in AI-generated responses (ChatGPT, Perplexity, etc.) and benchmarks them against competitors.

---

## What This Does

1. **Generate** hundreds of relevant search queries for a client using a template × value matrix
2. **Collect** AI responses to those queries via the `webish` module (OpenAI-backed)
3. **Analyze** responses to extract competitor mentions and citation links per business

---

## Repo Structure

```
Integrated_ai/
├── webish/              # AI-backed web-search module (OpenAI API + Playwright)
├── full_stack/          # Pipeline scripts: setup → collect → analyze
├── SBACO/               # Benchmarking suite and planning docs
├── [client folders]/    # One folder per client (query banks + output data)
│   ├── Channel_Islands_Adventure_Company/
│   ├── credimax/
│   ├── dirty_water_dough/
│   ├── conciegeone_net/
│   ├── jivacrete/
│   └── ...
├── Santa_Barbara_Common_Ground/  # Static website project (Firebase)
└── playground/          # Experiments, trading sims, research scripts
```

---

## Setup

### 1. Clone & enter the repo
```bash
git clone https://github.com/salmonhealer772/Integrated_ai.git
cd Integrated_ai
```

### 2. Create and activate a virtual environment
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 4. Configure environment variables
```bash
cp full_stack/.env.example .env
# Open .env and fill in OPENAI_API_KEY
```

---

## Running the Pipeline

> All commands run from the repo root (`Integrated_ai/`).

### Onboard a new client
```bash
python full_stack/setup.py
```
Creates a client folder with `query_template_bank.csv` and `value_bank.csv`.

### Collect AI responses
```bash
python full_stack/collect1.2.py <slug>
# Example:
python full_stack/collect1.2.py channel_islands_adventure_company
# Optional: limit number of questions for a quick test
python full_stack/collect1.2.py channel_islands_adventure_company --limit 20
```
Outputs `{slug}_aisodata{N}.csv` in the client folder.

### Analyze responses
```bash
python full_stack/analysis1.py <slug>
```
Enriches the CSV with competitor columns — which businesses were cited and how often.

---

## Data Files

Generated pipeline CSVs (`*_aisodata*.csv`, benchmark datasets) are **not tracked in git** — they are large and regenerable.

📁 **Share output CSVs with collaborators via the shared Google Drive folder.**

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for branching strategy, PR process, and commit conventions.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | ✅ | OpenAI API key for webish and analysis |
| `TWELVE_DATA_API_KEY` | Optional | TwelveData API (financial data scripts only) |
| `FIREBASE_TOKEN` | CI only | Firebase deploy token (set as GitHub secret) |
