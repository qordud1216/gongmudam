"""순수 파이썬 BM25 검색. 한글은 띄어쓰기·조사 변화가 많아 음절 2-gram 과 단어를 함께 색인한다.
외부 임베딩 모델이 필요 없어 폐쇄망·저사양 PC에서도 동작한다."""
from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[가-힣]+|[A-Za-z]+|\d+")


def tokenize(text: str) -> list[str]:
    toks = []
    for w in _TOKEN.findall(text.lower()):
        toks.append(w)
        if re.match(r"[가-힣]", w) and len(w) > 2:
            toks += [w[i:i + 2] for i in range(len(w) - 1)]
    return toks


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.4, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tfs = [Counter(tokenize(d)) for d in docs]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.avg = (sum(self.lens) / len(self.lens)) if self.lens else 0
        df = Counter()
        for tf in self.tfs:
            df.update(tf.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        out = []
        for tf, ln in zip(self.tfs, self.lens):
            s = 0.0
            for t in q:
                f = tf.get(t)
                if not f:
                    continue
                s += self.idf.get(t, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * ln / (self.avg or 1)))
            out.append(s)
        return out

    def top(self, query: str, k: int = 8, min_score: float = 0.0) -> list[tuple[int, float]]:
        sc = self.scores(query)
        ranked = sorted(range(len(sc)), key=lambda i: sc[i], reverse=True)
        return [(i, sc[i]) for i in ranked[:k] if sc[i] > min_score]
