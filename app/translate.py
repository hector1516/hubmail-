import json
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from .config import settings
from .db import get_conn

_DEEPL_HOST = "https://api-free.deepl.com/v2"
_MAX_TEXTS_PER_REQUEST = 50
_RESYNC_SECONDS = 3600


class DeepLError(Exception):
    def __init__(self, message, status=None, quota=False):
        super().__init__(message)
        self.status = status
        self.quota = quota


class _SegmentsParser(HTMLParser):
    _SKIP = {"script", "style", "pre", "code", "textarea"}

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.segments = []
        self._skip_stack = []

    def handle_starttag(self, tag, attrs):
        self.segments.append(("html", self.get_starttag_text()))
        if tag.lower() in self._SKIP:
            self._skip_stack.append(tag.lower())

    def handle_startendtag(self, tag, attrs):
        self.segments.append(("html", self.get_starttag_text()))

    def handle_endtag(self, tag):
        self.segments.append(("html", "</%s>" % tag))
        if tag.lower() in self._SKIP and self._skip_stack:
            self._skip_stack.pop()

    def handle_comment(self, data):
        self.segments.append(("html", "<!--%s-->" % data))

    def handle_decl(self, decl):
        self.segments.append(("html", "<!%s>" % decl))

    def handle_data(self, data):
        if self._skip_stack:
            self.segments.append(("html", data))
        else:
            self.segments.append(("text", data))


def is_configured() -> bool:
    return bool(settings.deepl_api_key)


def _raise_http_error(e):
    try:
        detail = e.read().decode("utf-8", "replace")
    except Exception:
        detail = ""
    if e.code == 456:
        raise DeepLError("Cuota de traducción agotada", status=456, quota=True)
    if e.code in (401, 403):
        raise DeepLError("Clave de traducción inválida o sin permisos", status=e.code)
    raise DeepLError(
        "Error del servicio de traducción (%s): %s" % (e.code, detail[:200]),
        status=e.code,
    )


def _post_json(path, fields):
    body = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        _DEEPL_HOST + path,
        data=body,
        method="POST",
        headers={
            "Authorization": "DeepL-Auth-Key " + settings.deepl_api_key,
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "HUBMail/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        _raise_http_error(e)
    except urllib.error.URLError as e:
        raise DeepLError(
            "No se pudo contactar el servicio de traducción: %s"
            % (e.reason or "error de red"),
            status=0,
        )


def _get_json(path):
    req = urllib.request.Request(
        _DEEPL_HOST + path,
        headers={
            "Authorization": "DeepL-Auth-Key " + settings.deepl_api_key,
            "User-Agent": "HUBMail/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        _raise_http_error(e)
    except urllib.error.URLError as e:
        raise DeepLError(
            "No se pudo contactar el servicio de traducción: %s"
            % (e.reason or "error de red"),
            status=0,
        )


def deepl_usage():
    data = _get_json("/usage")
    return int(data.get("character_count") or 0), int(data.get("character_limit") or 0)


def translate(texts, target="ES"):
    if not is_configured():
        raise DeepLError("Traducción no configurada", status=503)
    out = []
    for i in range(0, len(texts), _MAX_TEXTS_PER_REQUEST):
        chunk = texts[i : i + _MAX_TEXTS_PER_REQUEST]
        fields = [("target_lang", target)] + [("text", t) for t in chunk]
        data = _post_json("/translate", fields)
        trs = data.get("translations") or []
        if len(trs) != len(chunk):
            raise DeepLError("Respuesta de traducción inesperada", status=502)
        out.extend([(t.get("text") or "") for t in trs])
    return out


def _split(html):
    p = _SegmentsParser()
    p.feed(html or "")
    p.close()
    return p.segments


def translate_html(html, target="ES"):
    if not html:
        return html, 0
    segs = _split(html)
    to_send = [(i, v) for i, (k, v) in enumerate(segs) if k == "text" and v.strip()]
    if not to_send:
        return html, 0
    texts = [v for _, v in to_send]
    translated = translate(texts, target=target)
    tmap = dict(zip([i for i, _ in to_send], translated))
    out = []
    for i, (k, v) in enumerate(segs):
        if k == "text":
            out.append(tmap.get(i, v))
        else:
            out.append(v)
    return "".join(out), sum(len(t) for t in texts)


def estimate_chars(text, html=False):
    if not html:
        return len(text)
    segs = _split(text)
    return sum(len(v) for k, v in segs if k == "text" and v.strip())


def _stats():
    conn = get_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT ID, CharsUsed, CharsLimit, "
            "UNIX_TIMESTAMP(UpdatedAt) AS UpdatedTs "
            "FROM HUBMAIL_TranslationStats WHERE ID=1"
        )
        row = cur.fetchone()
        if not row:
            cur.execute(
                "INSERT INTO HUBMAIL_TranslationStats (ID, CharsUsed, CharsLimit) "
                "VALUES (1, 0, 0)"
            )
            conn.commit()
            row = {"ID": 1, "CharsUsed": 0, "CharsLimit": 0, "UpdatedTs": 0}
        return row
    finally:
        conn.close()


def _set_stats(used, limit):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE HUBMAIL_TranslationStats SET CharsUsed=%s, CharsLimit=%s WHERE ID=1",
            (used, limit),
        )
        conn.commit()
    finally:
        conn.close()


def check_quota(est):
    """Devuelve (ok, remaining). Si no hay contador local, usa DeepL en vivo."""
    try:
        row = _stats()
        used = int(row.get("CharsUsed") or 0)
        limit = int(row.get("CharsLimit") or 0)
        ts = int(row.get("UpdatedTs") or 0)
    except Exception:
        try:
            cc, cl = deepl_usage()
            remaining = max(0, cl - cc)
            return (cc + est <= cl), remaining
        except Exception:
            return True, None

    if limit <= 0 or (time.time() - ts) > _RESYNC_SECONDS:
        try:
            cc, cl = deepl_usage()
            if cl:
                used = max(used, cc)
                limit = cl
                _set_stats(used, limit)
        except Exception:
            pass
    remaining = max(0, limit - used)
    return (used + est <= limit), remaining


def balance():
    ok, _ = check_quota(0)
    try:
        row = _stats()
        used = int(row.get("CharsUsed") or 0)
        limit = int(row.get("CharsLimit") or 0)
    except Exception:
        try:
            used, limit = deepl_usage()
        except Exception:
            used, limit = 0, 0
    return {"used": used, "limit": limit, "remaining": max(0, limit - used)}


def record_usage(n):
    try:
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE HUBMAIL_TranslationStats SET CharsUsed = CharsUsed + %s "
                "WHERE ID=1",
                (int(n),),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def quota_exhausted():
    try:
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE HUBMAIL_TranslationStats SET CharsUsed = CharsLimit "
                "WHERE ID=1 AND CharsUsed < CharsLimit"
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass