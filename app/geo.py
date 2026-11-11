"""لغة الودجت حسب بلد الزائر: بحث محلي في قاعدة DB-IP Lite للبلدان.

يُطابَق عنوان IP ببلد في ملف على الخادم نفسه، ثم يُختار للبلد لغة من لغات بيان.
لا يُرسل العنوان إلى أي جهة، ولا يُحفظ، ولا يُحفظ البلد. إن لم يكن للبلد لغة
هنا أو لم يتوفّر الملف، تبقى لغة الودجت لغة الصفحة.

القاعدة «IP to Country Lite» من DB-IP (https://db-ip.com) برخصة CC BY 4.0،
ويُحدّثها الخادم مرة في الشهر.

The widget's language from the visitor's country: a local lookup in the DB-IP
Lite country database. The IP address is matched to a country in a file on
the server itself, and the country is matched to one of Bayan's languages.
The address is sent nowhere and is not stored, and neither is the country.
When the country has no language here, or the file is missing, the widget
keeps the page's language.

The database is DB-IP's "IP to Country Lite" (https://db-ip.com), licensed
CC BY 4.0, and the server refreshes it once a month.
"""
import gzip
import ipaddress
import logging
import os
import threading
import time
from datetime import date
from pathlib import Path

import httpx

from . import config, i18n

log = logging.getLogger("geo")

URL = "https://download.db-ip.com/free/dbip-country-lite-{month}.mmdb.gz"
MAX_AGE = 32 * 86400

# البلد ← اللغة. ما لم يُذكر يبقى بلغة الصفحة.
# Country → language. Anything not listed keeps the page's language.
_GROUPS = {
    "ar": "DZ BH KM DJ EG IQ JO KW LB LY MR MA OM PS QA SA SO SD SY TN AE YE EH",
    "pt-BR": "BR PT AO MZ CV GW ST TL",
    "es": "ES MX GT HN SV NI CR PA CU DO PR CO VE EC PE BO PY UY AR CL GQ",
    "fr": "FR BE LU MC SN CI ML BF NE TD CM CF CG CD GA GN BJ TG MG HT BI RW",
    "sw": "KE TZ UG",
    "hi": "IN",
    "ur": "PK",
    "fa": "IR AF TJ",
    "tr": "TR",
    "id": "ID",
}
COUNTRY_LANG = {cc: lang for lang, ccs in _GROUPS.items() for cc in ccs.split()}

_reader = None
_lock = threading.Lock()


def _path() -> Path:
    return Path(config.GEO_DB)


def load() -> bool:
    """يفتح الملف إن وُجد / Opens the file if it is there."""
    global _reader
    path = _path()
    if not path.exists():
        return False
    try:
        import maxminddb
        reader = maxminddb.open_database(str(path))
    except Exception:  # noqa: BLE001
        log.exception("تعذّر فتح قاعدة البلدان %s", path)
        return False
    with _lock:
        old, _reader = _reader, reader
    if old is not None:
        try:
            old.close()
        except Exception:  # noqa: BLE001
            pass
    return True


def country(ip: str) -> str | None:
    """رمز البلد (ISO) للعنوان، أو None / The address's ISO country code, or None."""
    reader = _reader
    if reader is None:
        return None
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if not addr.is_global:
        return None
    try:
        rec = reader.get(str(addr)) or {}
    except Exception:  # noqa: BLE001
        return None
    return ((rec.get("country") or {}).get("iso_code")) or None


def language(ip: str) -> str | None:
    """لغة بيان المناسبة لبلد العنوان، أو None.
    Bayan's language for the address's country, or None."""
    if not config.GEO_LANG:
        return None
    code = COUNTRY_LANG.get(country(ip) or "")
    return code if code in i18n.SUPPORTED_LANGUAGES else None


def _months(today: date) -> list[str]:
    prev = date(today.year - (today.month == 1), (today.month - 2) % 12 + 1, 1)
    return [today.strftime("%Y-%m"), prev.strftime("%Y-%m")]


def refresh(force: bool = False) -> bool:
    """ينزّل القاعدة إن غابت أو مضى عليها أكثر من شهر، ثم يفتحها. يجرّب ملف
    الشهر الحالي ثم السابق (يُنشر الملف في أول الشهر).
    Downloads the database when it is missing or over a month old, then opens
    it. Tries this month's file, then last month's (the file is published at
    the start of each month)."""
    path = _path()
    fresh = path.exists() and time.time() - path.stat().st_mtime < MAX_AGE
    if fresh and not force:
        return _reader is not None or load()
    path.parent.mkdir(parents=True, exist_ok=True)
    for month in _months(date.today()):
        url = URL.format(month=month)
        try:
            with httpx.Client(timeout=60, follow_redirects=True) as client:
                r = client.get(url)
            if r.status_code != 200:
                continue
            data = gzip.decompress(r.content)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)
            log.info("حُدّثت قاعدة البلدان من %s (%d KB)", url, len(data) // 1024)
            return load()
        except Exception:  # noqa: BLE001
            log.warning("تعذّر تنزيل قاعدة البلدان من %s", url, exc_info=True)
    return load()


def start() -> None:
    """عند الإقلاع ثم كل يوم، في الخلفية / At startup and then daily, in the
    background."""
    if not config.GEO_LANG:
        return

    def loop() -> None:
        while True:
            try:
                refresh()
            except Exception:  # noqa: BLE001
                log.exception("فشل تحديث قاعدة البلدان")
            time.sleep(86400)

    threading.Thread(target=loop, daemon=True, name="geo").start()
