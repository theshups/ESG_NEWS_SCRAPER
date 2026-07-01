from __future__ import annotations
import json, re, os, time, requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from src.logger import get_logger

log = get_logger(__name__)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.1"))
NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "180"))
TIMEOUT     = int(os.getenv("OLLAMA_TIMEOUT", "45"))
MAX_WORKERS = int(os.getenv("OLLAMA_MAX_WORKERS", "1"))
RETRY_COUNT = int(os.getenv("OLLAMA_RETRY_COUNT", "2"))
INPUT_LIMIT = int(os.getenv("OLLAMA_INPUT_LIMIT", "350"))

PREFERRED_MODELS = ["qwen2.5:1.5b", "qwen2.5:3b", "phi3.5:latest", "phi3.5"]

VALID_CATEGORIES = {
    "BRSR", "CBAM", "Carbon_Accounting", "Decarbonization",
    "Sustainability_Disclosure", "Environmental_Regulation",
    "Supply_Chain_Due_Diligence", "Governance_Compliance",
    "Material_ESG_Risk", "Carbon_Markets", "Irrelevant",
}
VALID_SENTIMENTS = {"positive", "negative", "neutral"}

ESG_KEYWORDS = [
    "brsr","sebi","ngrbc","cbam","carbon border","embedded emission",
    "scope 1","scope 2","scope 3","ghg","carbon footprint","emission factor",
    "iso 14064","lifecycle","lca","net zero","net-zero","sbti","decarboni",
    "transition plan","renewable energy","ppa","carbon capture","ccs",
    "csrd","esrs","issb","ifrs s1","ifrs s2","tcfd","gri ","cdp","double materiality",
    "eu ets","carbon tax","emissions trading","supplier emission","supply chain emission",
    "epd","greenwashing","esg audit","disclosure liability","carbon credit",
    "carbon offset","article 6","corsia","voluntary carbon","oil spill",
    "methane leak","climate litigation","sustainability report","climate disclosure",
    "esg report","green finance","climate policy","energy transition","climate risk",
    "stranded asset","biodiversity","deforestation","water risk","forced labour",
    "modern slavery","human rights","gender pay","just transition","sustainability",
]
IGNORE_SIGNALS = [
    "war","military","missile","drone attack","bombing","election","parliament",
    "football","cricket","tennis","olympic","celebrity","actor","movie",
    "box office","interest rate","inflation","gdp growth","tree plantation",
    "plastic awareness","wildlife","bird watching","csr campaign","recipe",
    "restaurant","tourism","fashion","real estate","murder","crime","arrested",
    "smartphone","iphone","gaming",
]

# Compact, directive prompt tuned for small models (qwen2.5:1.5b)
PROMPT_TEMPLATE = """Classify this ESG article for a carbon management consultancy. Reply with ONLY the JSON object below, nothing else.

Categories: BRSR, CBAM, Carbon_Accounting, Decarbonization, Sustainability_Disclosure, Environmental_Regulation, Supply_Chain_Due_Diligence, Governance_Compliance, Material_ESG_Risk, Carbon_Markets, Irrelevant

Rules:
- BRSR = Indian SEBI/BRSR/NGRBC reporting only
- CBAM = EU carbon border tax on imports only
- Carbon_Accounting = Scope 1/2/3, GHG inventory, footprint measurement
- Decarbonization = net zero, renewable energy, emission reduction plans
- Sustainability_Disclosure = CSRD, ESRS, ISSB, GRI, TCFD reporting standards
- Environmental_Regulation = EU ETS, carbon tax, emissions policy
- Supply_Chain_Due_Diligence = supplier emissions, Scope 3 data collection
- Governance_Compliance = greenwashing, ESG audit fraud, disclosure lawsuits
- Material_ESG_Risk = spills, leaks, contamination, climate litigation
- Carbon_Markets = carbon credits, offsets, voluntary carbon trading
- Irrelevant = anything else (war, sports, politics, lifestyle, generic news)

Sentiment rules - pick positive or negative whenever possible, neutral only if truly balanced:
- positive = achievement, investment, target met, growth, approval, partnership
- negative = fine, lawsuit, scandal, failure, damage, criticism, delay
- neutral = pure factual policy announcement with no clear outcome

Title: {{TITLE}}
Text: {{CONTENT}}

JSON (fill every field, action and reason must be real sentences not instructions):
{"category":"Decarbonization","relevant":true,"confidence":0.9,"sentiment":"positive","action":"short specific next step","reason":"short specific reason","primary_fields":"Climate Policy & Emissions","tags":"keyword1, keyword2"}"""


class OllamaClassifier:
    """ESG article classifier using local Ollama LLM. All inference logic lives here."""

    def __init__(self, host: str = None):
        self._host    = host or OLLAMA_HOST
        self._model   = None
        self._ready   = False
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        self._stats = {"total":0,"ollama":0,"fallback":0,"skipped":0,"errors":0,"retries":0,"total_time":0.0}

    @property
    def ready(self) -> bool:
        return self._ready

    def load(self) -> None:
        self._model = self._detect_model()
        self._ready = self._model is not None
        if self._ready:
            log.info("Ollama classifier ready — model: " + self._model + "  workers: " + str(MAX_WORKERS))
        else:
            log.warning("Ollama unavailable — keyword fallback active")

    def classify(self, title: str, body: str) -> dict:
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
        if not articles:
            return []
        results = [None] * len(articles)
        start = time.time()
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(self.classify, a.get("title",""), a.get("body","")): i for i, a in enumerate(articles)}
            done = 0
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    log.warning("batch worker error: " + str(e)[:60])
                    results[idx] = self._irrelevant_result()
                done += 1
                if done % 10 == 0:
                    elapsed = time.time() - start
                    rate = round(done/elapsed, 2) if elapsed else 0
                    eta = round((len(articles)-done)/rate) if rate else 0
                    log.info("batch progress: " + str(done) + "/" + str(len(articles)) + "  " + str(rate) + " art/s  eta " + str(eta) + "s")
        return results

    def print_stats(self) -> None:
        s = self._stats
        avg = round(s["total_time"]/s["ollama"], 1) if s["ollama"] else 0
        rate = round(s["ollama"]/s["total_time"], 2) if s["total_time"] else 0
        log.info("classifier stats  total=" + str(s["total"]) + "  ollama=" + str(s["ollama"])
                 + "  fallback=" + str(s["fallback"]) + "  skipped=" + str(s["skipped"])
                 + "  errors=" + str(s["errors"]) + "  retries=" + str(s["retries"])
                 + "  avg=" + str(avg) + "s  rate=" + str(rate) + " art/s")

    # ── internal ──────────────────────────────────────────────────────────

    def _detect_model(self):
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
        text = (title + " " + (body or "")).lower()
        esg_hits = sum(1 for kw in ESG_KEYWORDS if kw in text)
        ignore_hits = sum(1 for kw in IGNORE_SIGNALS if kw in text)
        if esg_hits == 0:
            return "irrelevant"
        if esg_hits >= 1 and ignore_hits >= 2:
            return "irrelevant"
        return "relevant"

    def _build_prompt(self, title: str, body: str) -> str:
        content = (body or "")[:INPUT_LIMIT]
        return PROMPT_TEMPLATE.replace("{{TITLE}}", (title or "")[:180]).replace("{{CONTENT}}", content)

    def _request(self, prompt: str) -> str:
        t = time.time()
        resp = self._session.post(
            self._host + "/api/generate",
            json={
                "model": self._model, "prompt": prompt, "stream": False, "think": False,
                "options": {"temperature": TEMPERATURE, "num_predict": NUM_PREDICT, "top_p": 0.9, "repeat_penalty": 1.1},
            },
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        self._stats["total_time"] += time.time() - t
        return resp.json().get("response", "")

    def _run_with_retry(self, title: str, body: str) -> dict:
        prompt = self._build_prompt(title, body)
        last_err = None
        for attempt in range(1, RETRY_COUNT + 1):
            try:
                raw = self._request(prompt)
                clean = self._clean_raw(raw)
                result = self._parse_and_normalize(clean)
                if result.get("category") in VALID_CATEGORIES:
                    self._stats["ollama"] += 1
                    return result
            except requests.exceptions.Timeout:
                last_err = "timeout"
            except Exception as e:
                last_err = str(e)[:60]
            if attempt < RETRY_COUNT:
                self._stats["retries"] += 1
                time.sleep(0.5)
        self._stats["errors"] += 1
        self._stats["fallback"] += 1
        log.debug("falling back for: " + (title or "")[:50] + " — " + str(last_err or "parse failed"))
        return self._keyword_fallback(title, body)

    def _clean_raw(self, raw: str) -> str:
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
        raw = re.sub(r"</?think>", "", raw)
        raw = re.sub(r"```json|```", "", raw)
        return raw.strip()

    def _parse_and_normalize(self, text: str) -> dict:
        if not text:
            return self._safe_default()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return self._safe_default()
        try:
            data = json.loads(m.group())
        except json.JSONDecodeError:
            data = self._repair_json(m.group())
            if not data:
                return self._safe_default()
        return self._normalize(data)

    def _repair_json(self, text: str) -> dict:
        try:
            text = re.sub(r",\s*([}\]])", r"\1", text)
            return json.loads(text)
        except Exception:
            result = {}
            for field in ["category","sentiment","action","reason","tags","primary_fields"]:
                m = re.search(r'"' + field + r'"\s*:\s*"([^"]*)"', text)
                if m:
                    result[field] = m.group(1)
            m_rel = re.search(r'"relevant"\s*:\s*(true|false)', text)
            if m_rel:
                result["relevant"] = m_rel.group(1) == "true"
            return result

    def _normalize(self, data: dict) -> dict:
        cat = data.get("category", "Irrelevant")
        if isinstance(cat, list):
            cat = cat[0] if cat else "Irrelevant"
        if cat not in VALID_CATEGORIES:
            cat = "Irrelevant"

        sent = data.get("sentiment", "neutral")
        if isinstance(sent, list):
            sent = sent[0] if sent else "neutral"
        if sent not in VALID_SENTIMENTS:
            sent = "neutral"

        pf = data.get("primary_fields", "")
        if isinstance(pf, list):
            pf = ", ".join(str(x) for x in pf)

        tags = data.get("tags", "")
        if isinstance(tags, list):
            tags = ", ".join(str(x) for x in tags)

        # critical fix — if model echoed instruction text instead of real content, blank it
        action = self._clean_field(data.get("action", ""))
        reason = self._clean_field(data.get("reason", ""))

        companies = data.get("companies", [])
        govt = data.get("govt_bodies", [])
        if isinstance(companies, str): companies = [companies] if companies else []
        if isinstance(govt, str): govt = [govt] if govt else []
        entities = json.dumps({"companies": companies, "govt_bodies": govt})

        relevant = bool(data.get("relevant", cat != "Irrelevant"))

        return {
            "category": cat, "relevant": relevant,
            "confidence": float(data.get("confidence", 0.0) or 0.0),
            "sentiment": sent, "action": action, "reason": reason,
            "primary_fields": pf, "entities": entities, "tags": tags,
            "priority": "none",
        }

    def _clean_field(self, value: str) -> str:
        """Strip placeholder/instruction leakage from LLM output. Blank if junk."""
        if not value or not isinstance(value, str):
            return ""
        v = value.strip()
        junk_markers = [
            "max 18 word", "max 25 word", "short specific", "fill every field",
            "one specific", "your action here", "your reason here", "n/a", "none",
        ]
        low = v.lower()
        if any(j in low for j in junk_markers) or len(v) < 3:
            return ""
        return v[:250]

    def _safe_default(self) -> dict:
        return {"category":"Irrelevant","relevant":False,"confidence":0.0,"sentiment":"neutral",
                "action":"","reason":"","primary_fields":"","entities":"{}","tags":"","priority":"none"}

    def _irrelevant_result(self) -> dict:
        r = self._safe_default()
        r["confidence"] = 0.95
        r["reason"] = "Pre-filtered as irrelevant"
        return r

    def _keyword_fallback(self, title: str, body: str) -> dict:
        text = (title + " " + (body or "")).lower()
        kw_map = {
            "BRSR": ["brsr","sebi","ngrbc","ccts","pat scheme"],
            "CBAM": ["cbam","carbon border adjustment","embedded emission"],
            "Carbon_Accounting": ["scope 1","scope 2","scope 3","ghg inventory","carbon footprint","emission factor","iso 14064"],
            "Decarbonization": ["net zero","net-zero","sbti","decarboni","transition plan","renewable energy","carbon capture"],
            "Sustainability_Disclosure": ["csrd","esrs","issb","ifrs s1","ifrs s2","tcfd","gri ","cdp","double materiality"],
            "Environmental_Regulation": ["eu ets","carbon tax","emissions trading","carbon price"],
            "Supply_Chain_Due_Diligence": ["supplier emission","scope 3 supplier","supply chain emission","due diligence"],
            "Governance_Compliance": ["greenwashing","esg audit","disclosure liability"],
            "Carbon_Markets": ["carbon credit","carbon offset","article 6","corsia"],
            "Material_ESG_Risk": ["oil spill","toxic contamination","methane leak","climate litigation"],
        }
        cat, rel = "Irrelevant", False
        for category, keywords in kw_map.items():
            if any(kw in text for kw in keywords):
                cat, rel = category, True
                break
        pos = ["progress","milestone","achieve","invest","launch","approve","record","success","growth","partnership","award"]
        neg = ["fail","scandal","miss","fine","penalt","breach","damage","crisis","setback","greenwash","lawsuit","violat"]
        sent = "neutral"
        if any(w in text for w in pos): sent = "positive"
        elif any(w in text for w in neg): sent = "negative"
        return {"category":cat,"relevant":rel,"confidence":0.5 if rel else 0.0,"sentiment":sent,
                "action":"" ,"reason":"Keyword fallback classification",
                "primary_fields":"","entities":"{}","tags":"","priority":"none"}