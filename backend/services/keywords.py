"""Offline keyword & hashtag helper.

No AI provider needed: extracts the most frequent meaningful words from a
caption or transcript. Honest and transparent — the API marks results as
offline so nobody mistakes them for AI output.
"""

from __future__ import annotations

import re
from collections import Counter

_WORD_RE = re.compile(r"[A-Za-z\u0600-\u06FF']+")

_EN_STOP = frozenset(
    """a an the and or but if then else when at by for with about into through
    during before after above below to from up down in out on off over under
    again further once here there all any both each few more most other some
    such no nor not only own same so than too very can will just don should now
    of is are was were be been being have has had having do does did doing
    would could ought i me my myself we our ours ourselves you your yours
    yourself he him his himself she her hers herself it its itself they them
    their theirs themselves what which who whom this that these those am as
    because until while this that it s t re ll ve m d ll""".split()
)

_UR_STOP = frozenset(
    """کا کی کے کو نے سے میں پر اور یہ وہ جو جس جن اس ان تھا تھی تھے ہیں ہے
    ہوگا ہوگی نہیں نہ بھی تو ہی صرف لئے لیے طرح طرح ساتھ بعد پہلے درمیان
    اوپر نیچے اندر باہر بہت کم زیادہ سب کچھ کوئی کیا کیوں کیسے کہ اگر جب تک
    پھر ابھی اب یہاں وہاں میرا میری میرے تمہارا تمہاری تمہارے اسکا اسکی ہم
    ہمارا ہماری ہمارے آپ کا آپکی مجھے تمہیں اسے انہیں جنہیں""".split()
)

_ROMAN_UR_STOP = frozenset(
    """ka ki ke ko ne se mein me par aur ye wo jo jis jin us un tha thi the
    hain hai hoga hogi nahi na bhi to hi sirf liye tarah sath baad pehle
    darmiyan upar neeche andar bahar bohat kam zyada sab kuch koi kya kyun
    kaise ke agar jab tak phir abhi ab yahan wahan mera meri mere tumhara
    tumhari tumhare uska uski hum hamara hamari hamare aap ka apki mujhe
    tumhein use unhein jinhein mera""".split()
)

_STOP = _EN_STOP | _UR_STOP | _ROMAN_UR_STOP


def extract_keywords(text: str, max_keywords: int = 10) -> tuple[list[str], list[str]]:
    """Return (keywords, hashtags) from raw text.

    Hashtags are '#'-prefixed ASCII-safe versions of the keywords; words that
    cannot be represented in ASCII are kept as plain keywords only.
    """
    words = _WORD_RE.findall((text or "").lower())
    freq = Counter(
        w for w in words if w not in _STOP and len(w) > 2 and not w.isdigit()
    )
    keywords = [w for w, _ in freq.most_common(max(1, min(max_keywords, 30)))]
    hashtags: list[str] = []
    for word in keywords:
        try:
            tag = word.encode("ascii").decode("ascii")
        except UnicodeEncodeError:
            continue
        tag = re.sub(r"[^a-z0-9]", "", tag)
        if len(tag) > 2:
            hashtags.append("#" + tag)
    return keywords, hashtags
