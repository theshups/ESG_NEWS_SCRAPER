from __future__ import annotations

from typing import Any

from src.components.base import BaseClassifier
from src.logger import get_logger

log = get_logger(__name__)

MODEL_ID   = "cross-encoder/nli-MiniLM2-L6-H768"
THRESHOLD  = 0.35   # lowered slightly so Mixed doesn't swallow everything
TEXT_LIMIT = 1_024

# --------------------------------------------------------------------------- #
#  Expanded keyword banks                                                       #
# --------------------------------------------------------------------------- #

_KEYWORDS: dict[str, list[str]] = {

    "Environmental": [
        # climate & temperature
        "climate change", "global warming", "climate crisis", "climate emergency",
        "climate risk", "climate action", "climate finance", "climate tech",
        "climate adaptation", "climate resilience", "climate justice",
        "1.5 degree", "2 degree", "temperature rise",

        # emissions
        "carbon", "co2", "carbon dioxide", "methane", "nitrous oxide",
        "greenhouse gas", "ghg", "emission", "scope 1", "scope 2", "scope 3",
        "net zero", "carbon neutral", "carbon negative", "carbon positive",
        "decarbonisation", "decarbonization", "low carbon", "zero carbon",
        "carbon footprint", "carbon offset", "carbon credit", "carbon market",
        "carbon price", "carbon tax", "emission trading", "cap and trade",
        "carbon budget", "carbon capture", "ccs", "ccus", "direct air capture",

        # energy
        "renewable energy", "clean energy", "green energy", "solar", "wind power",
        "offshore wind", "onshore wind", "wind turbine", "solar panel",
        "photovoltaic", "hydropower", "geothermal", "tidal energy", "biomass",
        "green hydrogen", "clean hydrogen", "energy transition", "energy storage",
        "battery storage", "electric vehicle", "ev", "charging infrastructure",
        "fossil fuel", "coal", "oil and gas", "natural gas", "stranded assets",
        "energy efficiency", "energy poverty",

        # nature & land
        "biodiversity", "ecosystem", "nature loss", "habitat destruction",
        "deforestation", "reforestation", "afforestation", "land use",
        "forest", "wetland", "coral reef", "ocean", "marine",
        "endangered species", "wildlife", "pollinator", "bee population",
        "nature-based solution", "tnfd", "natural capital",

        # water
        "water scarcity", "water stress", "water risk", "water management",
        "water pollution", "wastewater", "freshwater", "groundwater",
        "water efficiency", "drought",

        # waste & circular
        "waste", "recycling", "circular economy", "plastic waste", "single use plastic",
        "e-waste", "landfill", "composting", "zero waste", "packaging",

        # pollution
        "air pollution", "particulate matter", "pm2.5", "nitrogen oxide", "nox",
        "soil contamination", "chemical pollution", "toxic", "hazardous",

        # frameworks
        "tcfd", "tnfd", "paris agreement", "cop26", "cop27", "cop28", "cop29",
        "cop30", "kyoto", "ipcc", "ndc", "nationally determined",
        "net zero by 2050", "science based target", "sbti",
        "green taxonomy", "eu taxonomy", "sustainable finance",
    ],

    "Social": [
        # labour & workers
        "worker", "employee", "workforce", "labour", "labor", "staff",
        "living wage", "minimum wage", "fair wage", "pay gap", "gender pay gap",
        "equal pay", "wage theft", "labour rights", "worker rights",
        "trade union", "collective bargaining", "freedom of association",
        "child labour", "child labor", "forced labour", "forced labor",
        "modern slavery", "human trafficking", "bonded labour",
        "working conditions", "working hours", "overtime",
        "occupational health", "workplace safety", "health and safety",
        "injury rate", "fatality", "accident at work",

        # diversity equity inclusion
        "diversity", "inclusion", "equity", "dei", "esg diversity",
        "gender diversity", "racial diversity", "ethnic diversity",
        "lgbtq", "disability inclusion", "neurodiversity",
        "women in leadership", "female executive", "board diversity",
        "pay equity", "representation",

        # human rights
        "human rights", "human rights due diligence", "hrdd",
        "indigenous rights", "indigenous community", "free prior informed consent",
        "fpic", "land rights", "community rights", "displacement",

        # supply chain
        "supply chain", "supplier", "responsible sourcing", "ethical sourcing",
        "supply chain transparency", "supply chain audit",
        "conflict minerals", "artisanal mining",

        # community
        "community", "community engagement", "community investment",
        "local community", "social impact", "social value",
        "philanthropy", "corporate giving", "volunteering",
        "affordable housing", "food security", "access to healthcare",

        # health & wellbeing
        "employee wellbeing", "mental health", "burnout", "work life balance",
        "employee engagement", "staff turnover", "talent retention",
        "healthcare access", "public health", "pandemic", "covid",

        # product safety & access
        "product safety", "consumer protection", "data privacy",
        "access to medicine", "affordable medicine", "digital access",
        "financial inclusion",

        # frameworks
        "ungc", "un global compact", "un guiding principles", "ungp",
        "iso 45001", "sa8000",
    ],

    "Governance": [
        # board & leadership
        "board", "board of directors", "board composition", "board diversity",
        "independent director", "non-executive director", "ned",
        "chair", "chairman", "chairwoman", "board chair", "lead director",
        "board meeting", "board effectiveness", "board evaluation",
        "committee", "audit committee", "remuneration committee",
        "nomination committee", "risk committee", "esg committee",

        # executive pay
        "executive pay", "executive compensation", "ceo pay", "cfo pay",
        "pay ratio", "ceo to worker pay", "bonus", "long term incentive",
        "ltip", "share option", "remuneration", "golden parachute",

        # transparency & disclosure
        "transparency", "disclosure", "non-financial reporting",
        "integrated reporting", "sustainability reporting", "esg reporting",
        "annual report", "proxy statement", "materiality", "double materiality",

        # reporting frameworks
        "gri", "global reporting initiative", "sasb",
        "ifrs s1", "ifrs s2", "issb", "csrd", "csrd reporting",
        "nfrd", "sfdr", "sustainable finance disclosure",
        "tcfd governance", "integrated reporting",

        # audit
        "audit", "external audit", "internal audit", "auditor",
        "audit opinion", "audit quality", "assurance",

        # risk & compliance
        "risk management", "enterprise risk", "erm", "risk governance",
        "compliance", "regulatory compliance", "legal compliance",
        "code of conduct", "ethics", "business ethics", "integrity",

        # anti-corruption
        "anti-corruption", "anti-bribery", "bribery", "corruption",
        "fraud", "whistleblower", "speak up", "reporting channel",
        "money laundering", "sanctions", "fcpa", "uk bribery act",

        # shareholder
        "shareholder", "shareholder rights", "shareholder activism",
        "activist investor", "proxy vote", "say on pay", "agm",
        "annual general meeting", "investor engagement", "stewardship",
        "fiduciary duty", "asset manager", "institutional investor",

        # cybersecurity & data
        "cybersecurity", "data breach", "data privacy", "gdpr",
        "information security", "cyber risk", "ransomware",

        # tax
        "tax transparency", "tax avoidance", "tax haven",
        "country by country reporting", "cbcr",

        # regulators
        "sec", "fca", "esma", "eba", "ecb", "eu regulation",
        "sec climate", "sec esg", "mandatory reporting",
    ],
}


# --------------------------------------------------------------------------- #
#  KeywordClassifier — fast, offline, no model download                        #
# --------------------------------------------------------------------------- #

class KeywordClassifier(BaseClassifier):

    _ready = False

    def load(self) -> None:                             # override
        if not self._ready:
            total = sum(len(v) for v in _KEYWORDS.values())
            log.info(f"keyword classifier ready  ({total} keywords across 3 pillars)")
            KeywordClassifier._ready = True

    def classify_one(self, text: str) -> dict[str, Any]:   # override
        if not text:
            return _empty()

        lower = text.lower()
        hits  = {
            label: sum(1 for kw in bank if kw in lower)
            for label, bank in _KEYWORDS.items()
        }
        total = sum(hits.values()) or 1
        scores = {k: round(v / total, 4) for k, v in hits.items()}
        category = self.pick_winner(scores, THRESHOLD)

        return {
            "category":   category,
            "confidence": scores.get(category, 0.0),
            "scores":     scores,
        }

    def classify_batch(self, texts: list[str]) -> list[dict[str, Any]]:  # override
        return [self.classify_one(t) for t in texts]


# --------------------------------------------------------------------------- #
#  HuggingFaceClassifier — NLI model, auto-degrades to keyword on failure      #
# --------------------------------------------------------------------------- #

class HuggingFaceClassifier(BaseClassifier):

    def __init__(self, model: str = MODEL_ID, device: int = -1):
        self._model_id = model
        self._device   = device
        self._pipe     = None
        self._fallback: KeywordClassifier | None = None

    def load(self) -> None:    # override
        if self._pipe or self._fallback:
            return
        try:
            from transformers import pipeline
            log.info(f"loading  {self._model_id}  (device={'CPU' if self._device < 0 else f'GPU:{self._device}'})")
            self._pipe = pipeline(
                "zero-shot-classification",
                model=self._model_id,
                device=self._device,
                tokenizer_kwargs={"truncation": True, "max_length": 512},
            )
            log.info("model ready")
        except Exception as e:
            log.warning(f"HuggingFace model unavailable ({e}) — using keyword classifier instead")
            self._fallback = KeywordClassifier()
            self._fallback.load()

    def classify_one(self, text: str) -> dict[str, Any]:   # override
        if self._fallback:
            return self._fallback.classify_one(text)
        text = (text or "")[:TEXT_LIMIT]
        if not text.strip():
            return _empty()
        try:
            raw    = self._pipe(text, candidate_labels=self.ESG_LABELS, multi_label=False)
            scores = {k: round(v, 4) for k, v in zip(raw["labels"], raw["scores"])}
            cat    = self.pick_winner(scores, THRESHOLD)
            return {"category": cat, "confidence": scores.get(cat, 0.0), "scores": scores}
        except Exception as e:
            log.warning(f"inference error: {e}")
            return _empty()

    def classify_batch(self, texts: list[str]) -> list[dict[str, Any]]:   # override — native HF batch
        if self._fallback:
            return self._fallback.classify_batch(texts)

        cleaned = [(t or "")[:TEXT_LIMIT] for t in texts]
        results = [_empty()] * len(cleaned)
        active  = [(i, t) for i, t in enumerate(cleaned) if t.strip()]
        if not active:
            return results

        try:
            raw_batch = self._pipe(
                [t for _, t in active],
                candidate_labels=self.ESG_LABELS,
                multi_label=False,
            )
            if isinstance(raw_batch, dict):
                raw_batch = [raw_batch]
            for (i, _), raw in zip(active, raw_batch):
                scores    = {k: round(v, 4) for k, v in zip(raw["labels"], raw["scores"])}
                cat       = self.pick_winner(scores, THRESHOLD)
                results[i] = {"category": cat, "confidence": scores.get(cat, 0.0), "scores": scores}
        except Exception as e:
            log.warning(f"batch inference failed: {e}")

        return results


def _empty() -> dict[str, Any]:
    return {
        "category":   "Mixed",
        "confidence": 0.0,
        "scores":     {k: 0.0 for k in BaseClassifier.ESG_LABELS},
    }
