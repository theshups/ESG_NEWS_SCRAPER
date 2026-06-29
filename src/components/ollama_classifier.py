from __future__ import annotations
import json, re, os, time, requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from src.logger import get_logger

log = get_logger(__name__)

# ── configuration ──────────────────────────────────────────────────────────
OLLAMA_HOST    = os.getenv("OLLAMA_HOST", "http://localhost:11434")
TEMPERATURE    = float(os.getenv("OLLAMA_TEMPERATURE", "0.05"))
NUM_PREDICT    = int(os.getenv("OLLAMA_NUM_PREDICT", "200"))
TIMEOUT     = int(os.getenv("OLLAMA_TIMEOUT", "60"))
MAX_WORKERS = int(os.getenv("OLLAMA_MAX_WORKERS", "1"))
RETRY_COUNT    = int(os.getenv("OLLAMA_RETRY_COUNT", "2"))
INPUT_LIMIT = int(os.getenv("OLLAMA_INPUT_LIMIT", "400"))

PREFERRED_MODELS = [
    "qwen2.5:1.5b", "phi3.5:latest", "phi3.5",
    "qwen2.5:3b", "qwen2.5:latest",
    "qwen2.5:1.5b",
]

VALID_CATEGORIES = {
    "BRSR", "CBAM", "Carbon_Accounting", "Decarbonization",
    "Sustainability_Disclosure", "Environmental_Regulation",
    "Supply_Chain_Due_Diligence", "Governance_Compliance",
    "Material_ESG_Risk", "Carbon_Markets", "Irrelevant",
}

VALID_SENTIMENTS = {"positive", "negative", "neutral"}

# ── keyword pre-filter ─────────────────────────────────────────────────────
ESG_KEYWORDS = [
    "brsr","brsr core","sebi","ngrbc","cbam","carbon border","embedded emission",
    "scope 1","scope 2","scope 3","ghg","carbon footprint","emission factor",
    "iso 14064","lifecycle","lca","net zero","net-zero","sbti","decarboni",
    "transition plan","renewable energy","ppa","carbon capture","ccs",
    "csrd","esrs","issb","ifrs s1","ifrs s2","tcfd","gri","cdp","double materiality",
    "eu ets","carbon tax","emissions trading","supplier emission","supply chain emission",
    "epd","greenwashing","esg audit","disclosure liability","carbon credit",
    "carbon offset","article 6","corsia","voluntary carbon","oil spill",
    "methane leak","climate litigation","sustainability report","climate disclosure",
    "esg report","green finance","climate policy","energy transition","climate risk",
    "stranded asset","biodiversity","deforestation","water risk","forced labour",
    "modern slavery","human rights","gender pay","just transition",
]

IGNORE_SIGNALS = [
    "war","military","missile","drone attack","bombing",
    "election","parliament","political party","vote",
    "football","cricket","tennis","olympic",
    "celebrity","actor","movie","box office",
    "interest rate","inflation","gdp growth",
    "tree plantation","tree planting drive","plastic awareness",
    "wildlife story","animal rescue","bird watching",
    "csr campaign","corporate social responsibility event",
]

# ── prompt ─────────────────────────────────────────────────────────────────
PROMPT_TEMPLATE = """/no_think
You are an expert ESG analyst classifying news for a carbon management company.

The company specialises in:
- Indian BRSR and BRSR Core reporting
- EU CBAM compliance and embedded emissions
- Corporate carbon footprints: Scope 1, Scope 2, Scope 3
- Decarbonisation strategy and net zero transitions
- CSRD, ISSB, GRI, TCFD sustainability disclosure
- Carbon markets, credits, and offsets
- Supplier emissions and value chain due diligence

CATEGORY — pick exactly one:
BRSR: SEBI, BRSR Core, Indian listed companies, NGRBC, Indian Carbon Market, CCTS, PAT, BEE
CBAM: EU Carbon Border Adjustment, embedded emissions, CBAM certificates, CBAM sectors
Carbon_Accounting: Scope 1/2/3, GHG inventory, emission factors, LCA, ISO 14064, carbon footprint
Decarbonization: net zero, SBTi, transition plans, renewable energy, CCS, green hydrogen, PPAs
Sustainability_Disclosure: CSRD, ESRS, ISSB, IFRS S1/S2, GRI, TCFD, CDP, double materiality
Environmental_Regulation: EU ETS, carbon tax, emissions trading, carbon pricing policy
Supply_Chain_Due_Diligence: supplier emissions, Scope 3 data, EPDs, due diligence laws
Governance_Compliance: greenwashing enforcement, ESG audit, disclosure liability, climate litigation
Material_ESG_Risk: oil spills, methane leaks, contamination, climate physical damage
Carbon_Markets: carbon credits, offsets, Article 6, CORSIA, voluntary carbon markets
Irrelevant: war, politics, sports, lifestyle, generic CSR, tree planting, wildlife, celebrity

IGNORE unless directly ESG compliance relevant:
- CSR events, tree planting drives, plastic awareness days
- Wildlife or nature stories without regulatory angle
- Political commentary, elections, military news
- Generic renewable energy without business ESG angle

SENTIMENT:
positive: sustainability progress, targets met, good investment news
negative: failures, scandals, penalties, environmental damage, greenwashing exposed
neutral: policy updates, research, framework announcements, mixed outcomes

PRIMARY FIELDS (comma-separated, all that apply):
Climate Policy & Emissions | Green Finance & Investments | Supply Chain Ethics | Diversity Equity & Inclusion | Regulatory Compliance

Title: {{TITLE}}
Content: {{CONTENT}}

Return ONLY valid JSON:
{"category":"...","relevant":true,"confidence":0.85,"sentiment":"neutral","action":"max 18 words","reason":"max 25 words","primary_fields":"...","companies":[],"govt_bodies":[],"tags":"..."}"""


class OllamaClassifier:
    """
    Production ESG article classifier using Ollama local LLM.

    All Ollama logic lives here:
      - model detection
      - prompt construction
      - HTTP requests with session reuse
      - retries and timeout handling
      - JSON parsing and repair
      - normalization
      - concurrent batch inference
      - streaming
      - fallback handling
      - statistics

    Usage:
        clf = OllamaClassifier()
        clf.load()
        result = clf.classify(title, body)
        results = clf.classify_batch(articles)
    """

    def __init__(self, host: str = None):
        self._host    = host or OLLAMA_HOST
        self._model   = None
        self._ready   = False
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        self._stats   = {
            "total": 0, "ollama": 0, "fallback": 0,
            "skipped": 0, "errors": 0, "retries": 0,
            "total_time": 0.0,
        }

    # ── public api ─────────────────────────────────────────────────────────

    @property
    def ready(self) -> bool:
        return self._ready

    def load(self) -> None:
        """Detect available Ollama model and prepare classifier."""
        self._model = self._detect_model()
        if self._model:
            self._ready = True
            log.info("Ollama classifier ready — model: " + self._model
                     + "  workers: " + str(MAX_WORKERS))
        else:
            log.warning("Ollama unavailable — keyword fallback active")

    def classify(self, title: str, body: str) -> dict:
        """Classify a single article. Thread-safe."""
        self._stats["total"] += 1
        signal = self._prefilter(title, body)
        if signal == "irrelevant":
            self._stats["skipped"] += 1
            return self._irrelevant_result()
        if not self._ready:
            self._stats["fallback"] += 1
            return self._keyword_fallback(title, body)
        return self._run_with_retry(title, body)

    def classify_batch(self, articles: list[dict]) -> list[dict]:
        """
        Concurrent batch classification using ThreadPoolExecutor.

        articles: list of dicts with 'title' and 'body' keys
        Returns: list of result dicts in same order as input

        Thread safety: each worker calls self.classify() which is thread-safe.
        Workers never touch SQLAlchemy sessions.
        """
        if not articles:
            return []

        results  = [None] * len(articles)
        start    = time.time()

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            future_to_idx = {
                pool.submit(self.classify, a.get("title",""), a.get("body","")): i
                for i, a in enumerate(articles)
            }
            done = 0
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    log.warning("batch worker error: " + str(e)[:60])
                    results[idx] = self._irrelevant_result()
                done += 1
                if done % 10 == 0:
                    elapsed = time.time() - start
                    rate    = round(done / elapsed, 2)
                    eta     = round((len(articles) - done) / rate) if rate > 0 else 0
                    log.info("batch progress: " + str(done) + "/" + str(len(articles))
                             + "  " + str(rate) + " art/s  eta " + str(eta) + "s")

        return results

    def classify_stream(self, title: str, body: str) -> dict:
        """
        Classify with live token streaming to stdout.
        Shows Ollama generating the response in real time.
        """
        if not self._ready:
            return self._keyword_fallback(title, body)

        prompt = self._build_prompt(title, body)
        raw    = ""
        in_think = False

        try:
            resp = self._session.post(
                self._host + "/api/generate",
                json=self._build_payload(prompt, stream=True),
                stream=True,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()

            import sys
            sys.stdout.write("  ")
            sys.stdout.flush()

            for line in resp.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                token = chunk.get("response", "")
                if "<think>" in token:
                    in_think = True
                if not in_think:
                    raw += token
                    sys.stdout.write(token)
                    sys.stdout.flush()
                if "</think>" in token:
                    in_think = False
                if chunk.get("done"):
                    break

            sys.stdout.write("\n")
            sys.stdout.flush()

        except Exception as e:
            log.warning("stream error: " + str(e)[:60])
            return self._keyword_fallback(title, body)

        return self._parse_and_normalize(self._clean_raw(raw))

    def print_stats(self) -> None:
        s    = self._stats
        avg  = round(s["total_time"] / s["ollama"], 1) if s["ollama"] else 0
        rate = round(s["ollama"] / s["total_time"], 2) if s["total_time"] > 0 else 0
        log.info(
            "classifier stats"
            + "  total=" + str(s["total"])
            + "  ollama=" + str(s["ollama"])
            + "  fallback=" + str(s["fallback"])
            + "  skipped=" + str(s["skipped"])
            + "  errors=" + str(s["errors"])
            + "  retries=" + str(s["retries"])
            + "  avg=" + str(avg) + "s"
            + "  rate=" + str(rate) + " art/s"
        )

    # ── internal methods ───────────────────────────────────────────────────

    def _detect_model(self) -> str | None:
        """Detect best available Ollama model."""
        try:
            r = self._session.get(self._host + "/api/tags", timeout=5)
            if r.status_code != 200:
                return None
            models = [m["name"] for m in r.json().get("models", [])]
            if not models:
                return None
            log.info("Ollama models: " + str(models))
            for p in PREFERRED_MODELS:
                if p in models:
                    return p
            return models[0]
        except Exception as e:
            log.warning("model detection failed: " + str(e))
            return None

    def _prefilter(self, title: str, body: str) -> str:
        """
        Fast keyword pre-filter — microsecond speed.
        Returns: 'irrelevant' | 'relevant' | 'unsure'
        """
        text       = (title + " " + (body or "")).lower()
        esg_hits   = sum(1 for kw in ESG_KEYWORDS if kw in text)
        ignore_hits = sum(1 for kw in IGNORE_SIGNALS if kw in text)
        if esg_hits == 0 and ignore_hits >= 1:
            return "irrelevant"
        if esg_hits >= 2:
            return "relevant"
        return "unsure"

    def _build_prompt(self, title: str, body: str) -> str:
        """Construct classification prompt."""
        content = (body or "")[:INPUT_LIMIT]
        return (
            PROMPT_TEMPLATE
            .replace("{{TITLE}}", (title or "")[:200])
            .replace("{{CONTENT}}", content)
        )

    def _build_payload(self, prompt: str, stream: bool = False) -> dict:
        """Build Ollama API payload."""
        return {
            "model":  self._model,
            "prompt": prompt,
            "stream": stream,
            "think":  False,
            "options": {
                "temperature":    TEMPERATURE,
                "num_predict":    NUM_PREDICT,
                "top_p":          0.9,
                "repeat_penalty": 1.1,
            },
        }

    def _request(self, prompt: str) -> str:
        """Single HTTP request to Ollama. Returns raw response text."""
        t = time.time()
        resp = self._session.post(
            self._host + "/api/generate",
            json=self._build_payload(prompt, stream=False),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        self._stats["total_time"] += time.time() - t
        return resp.json().get("response", "")

    def _run_with_retry(self, title: str, body: str) -> dict:
        """Run classification with retry logic."""
        prompt  = self._build_prompt(title, body)
        last_err = None

        for attempt in range(1, RETRY_COUNT + 1):
            try:
                raw    = self._request(prompt)
                clean  = self._clean_raw(raw)
                result = self._parse_and_normalize(clean)
                if result.get("category") in VALID_CATEGORIES:
                    self._stats["ollama"] += 1
                    return result
                log.debug("attempt " + str(attempt) + " returned invalid category")
            except requests.exceptions.Timeout:
                last_err = "timeout"
                log.warning("Ollama timeout attempt " + str(attempt) + ": " + (title or "")[:40])
            except Exception as e:
                last_err = str(e)[:60]
                log.warning("Ollama error attempt " + str(attempt) + ": " + last_err)

            if attempt < RETRY_COUNT:
                self._stats["retries"] += 1
                time.sleep(1.0 * attempt)

        self._stats["errors"] += 1
        self._stats["fallback"] += 1
        log.warning("all retries failed for: " + (title or "")[:50] + " — " + str(last_err or "empty response"))
        return self._keyword_fallback(title, body)

    def _clean_raw(self, raw: str) -> str:
        """Strip thinking tokens and markdown fences."""
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
        raw = re.sub(r"</?think>", "", raw)
        raw = re.sub(r"```json|```", "", raw)
        return raw.strip()

    def _parse_and_normalize(self, text: str) -> dict:
        """Parse JSON response and normalize all fields."""
        if not text:
            return self._safe_default()

        # try direct parse
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return self._repair_and_parse(text)

        try:
            data = json.loads(m.group())
        except json.JSONDecodeError:
            data = self._repair_and_parse(text)
            if not data:
                return self._safe_default()

        return self._normalize(data)

    def _repair_and_parse(self, text: str) -> dict:
        """Attempt to repair malformed JSON."""
        try:
            # fix trailing commas
            text = re.sub(r",\s*([}\]])", r"\1", text)
            # fix unquoted values
            text = re.sub(r':\s*([^",\{\[\d\s][^",\}\]]*?)([,\}])', r': "\1"\2', text)
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                return json.loads(m.group())
        except Exception:
            pass

        # extract fields manually as last resort
        result = {}
        for field in ["category","sentiment","action","reason","tags","primary_fields"]:
            m = re.search(r'"' + field + r'"\s*:\s*"([^"]*)"', text)
            if m:
                result[field] = m.group(1)
        m_rel = re.search(r'"relevant"\s*:\s*(true|false)', text)
        if m_rel:
            result["relevant"] = m_rel.group(1) == "true"
        m_conf = re.search(r'"confidence"\s*:\s*([\d.]+)', text)
        if m_conf:
            result["confidence"] = float(m_conf.group(1))

        return result if result else {}

    def _normalize(self, data: dict) -> dict:
        """Normalize all fields to correct types."""
        # category
        cat = data.get("category", "Irrelevant")
        if isinstance(cat, list):
            cat = cat[0] if cat else "Irrelevant"
        if cat not in VALID_CATEGORIES:
            cat = "Irrelevant"

        # sentiment
        sent = data.get("sentiment", "neutral")
        if isinstance(sent, list):
            sent = sent[0] if sent else "neutral"
        if sent not in VALID_SENTIMENTS:
            sent = "neutral"

        # primary_fields
        pf = data.get("primary_fields", "")
        if isinstance(pf, list):
            pf = ", ".join(str(x) for x in pf)

        # tags
        tags = data.get("tags", "")
        if isinstance(tags, list):
            tags = ", ".join(str(x) for x in tags)

        # entities
        companies   = data.get("companies", [])
        govt_bodies = data.get("govt_bodies", [])
        if isinstance(companies, str):
            companies = [companies]
        if isinstance(govt_bodies, str):
            govt_bodies = [govt_bodies]
        entities = json.dumps({"companies": companies, "govt_bodies": govt_bodies})

        # relevance
        relevant = bool(data.get("relevant", cat != "Irrelevant"))

        return {
            "category":      cat,
            "relevant":      relevant,
            "confidence":    float(data.get("confidence", 0.0)),
            "sentiment":     sent,
            "action":        str(data.get("action", "No action."))[:200],
            "reason":        str(data.get("reason", ""))[:300],
            "primary_fields":pf,
            "entities":      entities,
            "tags":          tags,
            "priority":      "none",
        }

    def _safe_default(self) -> dict:
        return {
            "category": "Irrelevant", "relevant": False,
            "confidence": 0.0, "sentiment": "neutral",
            "action": "No action.", "reason": "Parse failed.",
            "primary_fields": "", "entities": "{}",
            "tags": "", "priority": "none",
        }

    def _irrelevant_result(self) -> dict:
        r = self._safe_default()
        r["confidence"] = 0.95
        r["reason"]     = "Pre-filtered as irrelevant."
        return r

    def _keyword_fallback(self, title: str, body: str) -> dict:
        """Fast keyword-based classification when Ollama unavailable."""
        text = (title + " " + (body or "")).lower()
        kw_map = {
            "BRSR":                      ["brsr","brsr core","sebi","ngrbc","ccts","pat scheme"],
            "CBAM":                      ["cbam","carbon border adjustment","embedded emission"],
            "Carbon_Accounting":         ["scope 1","scope 2","scope 3","ghg inventory","carbon footprint","emission factor","iso 14064"],
            "Decarbonization":           ["net zero","net-zero","sbti","decarboni","transition plan","renewable energy","carbon capture"],
            "Sustainability_Disclosure": ["csrd","esrs","issb","ifrs s1","ifrs s2","tcfd","gri","cdp","double materiality"],
            "Environmental_Regulation":  ["eu ets","carbon tax","emissions trading","carbon price"],
            "Supply_Chain_Due_Diligence":["supplier emission","scope 3 supplier","supply chain emission","due diligence"],
            "Governance_Compliance":     ["greenwashing","esg audit","disclosure liability"],
            "Carbon_Markets":            ["carbon credit","carbon offset","article 6","corsia"],
            "Material_ESG_Risk":         ["oil spill","toxic contamination","methane leak","climate litigation"],
        }
        cat, rel = "Irrelevant", False
        for category, keywords in kw_map.items():
            if any(kw in text for kw in keywords):
                cat, rel = category, True
                break

        pos = ["progress","milestone","achieve","invest","launch","approve","record","success"]
        neg = ["fail","scandal","miss","fine","penalt","breach","damage","crisis","setback","greenwash"]
        sent = "neutral"
        if any(w in text for w in pos): sent = "positive"
        elif any(w in text for w in neg): sent = "negative"

        return {
            "category": cat, "relevant": rel,
            "confidence": 0.5 if rel else 0.0,
            "sentiment": sent, "priority": "none",
            "action": "Review for business relevance." if rel else "No action.",
            "reason": "Keyword fallback — Ollama unavailable.",
            "primary_fields": "", "entities": "{}",  "tags": "",
        }