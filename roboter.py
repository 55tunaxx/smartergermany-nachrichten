# -*- coding: utf-8 -*-
# ═══════════════════════════════════════════════════════════════
#  SmarterGermany Nachrichten-Roboter
#  RSS toplar → aynı haberleri birleştirir → Gemini ÖZGÜN Almanca
#  metin yazar → nachrichten.json üretir. GitHub Actions'ta 30 dk'da
#  bir çalışır; uygulama bu JSON'u okur (kaynak linki korunur).
#  GEMINI_KEY yoksa/koparsa RSS özetiyle devam eder — robot durmaz.
# ═══════════════════════════════════════════════════════════════
import json
import os
import re
import socket
import time
import urllib.request

import feedparser

socket.setdefaulttimeout(15)  # asılı kalan kaynak tüm robotu bekletmesin

CIKTI = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "nachrichten.json")
GEMINI_KEY = os.environ.get("GEMINI_KEY", "").strip()
# Sıra önemli: önce bedava kotası yüksek hafif modeller denenir.
GEMINI_MODELLER = ["gemini-2.5-flash-lite", "gemini-2.0-flash",
                   "gemini-2.5-flash"]
YAZIM_SINIRI = 24          # tek çalışmada en fazla bu kadar YENİ haber yazılır
PARTI = 12                 # Gemini'ye tek istekte kaç haber verilir
UST_SINIR = 90             # JSON'a girecek toplam haber

QUELLEN = [
    ("tagesschau", "https://www.tagesschau.de/index~rss2.xml", None),
    ("ntv", "https://www.n-tv.de/politik/rss", "Politik"),
    ("ntv", "https://www.n-tv.de/wirtschaft/rss", "Wirtschaft"),
    ("ntv", "https://www.n-tv.de/sport/rss", "Sport"),
    ("ntv", "https://www.n-tv.de/technik/rss", "Technik"),
    ("ntv", "https://www.n-tv.de/panorama/rss", "Panorama"),
    ("SPIEGEL", "https://www.spiegel.de/politik/index.rss", "Politik"),
    ("SPIEGEL", "https://www.spiegel.de/wirtschaft/index.rss", "Wirtschaft"),
    ("SPIEGEL", "https://www.spiegel.de/ausland/index.rss", "Ausland"),
    ("SPIEGEL", "https://www.spiegel.de/sport/index.rss", "Sport"),
    ("SPIEGEL", "https://www.spiegel.de/netzwelt/index.rss", "Technik"),
    ("sportschau", "https://www.sportschau.de/index~rss2.xml", "Sport"),
    ("kicker", "https://newsfeed.kicker.de/news/aktuell", "Sport"),
    ("heise online", "https://www.heise.de/rss/heise.rdf", "Technik"),
    ("golem.de", "https://rss.golem.de/rss.php?feed=RSS2.0", "Technik"),
    ("WELT", "https://www.welt.de/feeds/latest.rss", None),
    ("FAZ", "https://www.faz.net/rss/aktuell/", None),
    ("DW", "https://rss.dw.com/rdf/rss-de-all", "Ausland"),
]


def html_temizle(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    for a, b in [("&amp;", "&"), ("&quot;", '"'), ("&#039;", "'"),
                 ("&apos;", "'"), ("&lt;", "<"), ("&gt;", ">"),
                 ("&nbsp;", " ")]:
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def kategorie_aus_link(link):
    l = link.lower()
    if "/sport" in l:
        return "Sport"
    if "/wirtschaft" in l or "/finanzen" in l:
        return "Wirtschaft"
    if "/ausland" in l:
        return "Ausland"
    if "/politik" in l or "/inland" in l:
        return "Politik"
    if any(k in l for k in ("/netzwelt", "/technik", "/digital", "/wissen")):
        return "Technik"
    if any(k in l for k in ("/panorama", "/vermischtes", "/kultur")):
        return "Panorama"
    return "Politik"


def feeds_topla():
    simdi = time.time()
    haberler = []
    for name, url, kategorie in QUELLEN:
        try:
            f = feedparser.parse(url, agent="SmarterGermany-Roboter/1.0")
            for e in f.entries[:30]:
                titel = html_temizle(getattr(e, "title", ""))
                link = getattr(e, "link", "") or ""
                if not titel or not link or titel.startswith("Anzeige:"):
                    continue
                t = getattr(e, "published_parsed", None) or getattr(
                    e, "updated_parsed", None)
                zeit = time.mktime(t) if t else simdi
                alter = simdi - zeit
                if alter > 3 * 86400 or alter < -5400:
                    continue
                haberler.append({
                    "t": titel,
                    "b": html_temizle(getattr(e, "summary", "")) or titel,
                    "l": link,
                    "k": kategorie or kategorie_aus_link(link),
                    "z": int(zeit * 1000),
                    "i": None,
                    "e": "eilmeldung" in link or "+++" in titel,
                    "q": [name],
                })
        except Exception as hata:
            print(f"  ! {name} atlandı: {hata}")
    return haberler


def anlamli_kelimeler(titel):
    kelimeler = re.sub(r"[^a-zäöüß0-9 ]", " ", titel.lower()).split()
    return {k for k in kelimeler if len(k) > 3}


def birlestir(haberler):
    """Aynı haberi farklı kaynaklardan tek kayda indirir (uygulamayla aynı mantık)."""
    gruplar = []
    for a in haberler:
        wa = anlamli_kelimeler(a["t"])
        katildi = False
        for g in gruplar:
            if abs(a["z"] - g["z"]) > 12 * 3600 * 1000:
                continue
            wg = anlamli_kelimeler(g["t"])
            kucuk = wa if len(wa) < len(wg) else wg
            if not kucuk:
                continue
            kesisim = len(wa & wg)
            if kesisim / len(kucuk) >= 0.6 and kesisim >= 3:
                if len(a["b"]) > len(g["b"]):
                    g["t"], g["b"], g["l"] = a["t"], a["b"], a["l"]
                g["q"] = sorted(set(g["q"]) | set(a["q"]))
                g["z"] = max(g["z"], a["z"])
                g["e"] = g["e"] or a["e"]
                katildi = True
                break
        if not katildi:
            gruplar.append(dict(a))
    return gruplar


def eski_yazilanlar():
    """Önceki çalışmada Gemini'nin yazdığı metinleri link üzerinden geri getirir
    (aynı haber her 30 dakikada bir yeniden yazılmasın — kota tasarrufu)."""
    if not os.path.exists(CIKTI):
        return {}
    try:
        with open(CIKTI, "r", encoding="utf-8") as f:
            eski = json.load(f)
        return {a["l"]: a for a in eski.get("artikel", [])
                if a.get("ki") is True}
    except Exception:
        return {}


def gemini_yaz(parti, model):
    """Bir grup habere özgün başlık+metin yazdırır. [{n,titel,text}] döner."""
    girdi = [{"n": i, "titel": h["t"], "info": h["b"][:400],
              "kategorie": h["k"]} for i, h in enumerate(parti)]
    istek = {
        "contents": [{"parts": [{"text": (
            "Du bist Nachrichtenredakteur der deutschen News-App "
            "SmarterGermany. Für jede Meldung unten schreibe KOMPLETT NEU "
            "und in EIGENEN Worten (nicht kopieren, nicht übersetzen):\n"
            "- 'titel': prägnante Schlagzeile, max. 10 Wörter, kein Clickbait\n"
            "- 'text': neutrale Zusammenfassung, 50-80 Wörter, sachlich, "
            "verständlich (B1-B2), keine Meinung, keine Übertreibung.\n"
            "Antworte NUR als JSON-Array: [{\"n\":0,\"titel\":\"...\","
            "\"text\":\"...\"}, ...]\n\nMeldungen:\n"
            + json.dumps(girdi, ensure_ascii=False))}]}],
        "generationConfig": {"response_mime_type": "application/json",
                             "temperature": 0.4,
                             "maxOutputTokens": 8192},
    }
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={GEMINI_KEY}")
    r = urllib.request.Request(
        url, data=json.dumps(istek).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=120) as cevap:
        yanit = json.load(cevap)
    metin = yanit["candidates"][0]["content"]["parts"][0]["text"].strip()
    # Bazı modeller JSON'u ``` çiti içinde döndürür — soy
    metin = re.sub(r"^```(json)?\s*|\s*```$", "", metin)
    return json.loads(metin)


def main():
    print("Feeds werden geladen...")
    haberler = birlestir(feeds_topla())
    haberler.sort(key=lambda h: h["z"], reverse=True)
    haberler = haberler[:UST_SINIR]
    print(f"{len(haberler)} Meldungen nach Bündelung.")

    onceki = eski_yazilanlar()
    yazilan, yeni_yazim = 0, 0
    for h in haberler:
        eski = onceki.get(h["l"])
        if eski:  # daha önce yazılmış — metni koru
            h["t"], h["b"], h["ki"] = eski["t"], eski["b"], True
            yazilan += 1
    yazilacak = [h for h in haberler if not h.get("ki")][:YAZIM_SINIRI]

    if GEMINI_KEY and yazilacak:
        model_sirasi = list(GEMINI_MODELLER)
        for i in range(0, len(yazilacak), PARTI):
            parti = yazilacak[i:i + PARTI]
            basarili = False
            for model in list(model_sirasi):
                try:
                    sonuc = gemini_yaz(parti, model)
                    for satir in sonuc:
                        h = parti[satir["n"]]
                        titel = (satir.get("titel") or "").strip()
                        text = (satir.get("text") or "").strip()
                        if len(text) > 80 and len(titel) > 8:
                            h["t"], h["b"], h["ki"] = titel, text, True
                            yeni_yazim += 1
                    print(f"  + {model}: {len(parti)} haber yazıldı")
                    basarili = True
                    break
                except Exception as hata:
                    detay = ""
                    if hasattr(hata, "read"):
                        try:
                            detay = hata.read().decode("utf-8")[:300]
                        except Exception:
                            pass
                    print(f"  ! {model} başarısız: {hata} {detay}")
                    # Çalışmayan modeli sıradan düş (sonuncusuysa kalsın)
                    if len(model_sirasi) > 1 and model in model_sirasi:
                        model_sirasi.remove(model)
            if not basarili:
                print("  ! Bu parti yazılamadı, RSS özetiyle kalıyor.")
            time.sleep(10)  # dakikalık istek limitine nazik davran
    elif not GEMINI_KEY:
        print("GEMINI_KEY yok — RSS özetleriyle devam (test modu).")

    with open(CIKTI, "w", encoding="utf-8") as f:
        json.dump({"stand": int(time.time() * 1000), "artikel": haberler},
                  f, ensure_ascii=False)
    print(f"OK: {len(haberler)} haber yazıldı "
          f"({yazilan} hazırdı, {yeni_yazim} yeni KI-metni).")


if __name__ == "__main__":
    main()
