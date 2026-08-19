import base64
import random
import unicodedata
from pathlib import Path

LOGO_FILE = "eccsa_trans_1080p.png"

IMG_DIRS = [
    Path(__file__).resolve().parent.parent / "img",
    Path.cwd() / "img",
    Path("/data/img"),
]

PHOTO_ALIASES = {
    "rosa": "rosy",
    "jose": "david",
}

NAME_OVERRIDES = {
    "jose salazar": "David Salazar",
}

PHRASES = [
    "La ingeniería no es solo ciencia: es el arte de dar soluciones donde otros solo ven problemas.",
    "La precisión en los detalles es lo que convierte un buen trabajo en un gran trabajo.",
    "La simplicidad es la máxima sofisticación.",
    "La calidad no es un acto, es un hábito.",
    "Medir es el primer paso para mejorar.",
    "La confiabilidad se diseña, se construye y se comprueba.",
    "El mantenimiento preventivo de hoy evita el paro costoso de mañana.",
    "La innovación distingue entre un líder y un seguidor.",
    "La excelencia no es una meta, es un camino constante de mejora.",
    "Cada engrane cuenta en la maquinaria del éxito.",
    "La mejor pieza es la que trabaja en silencio y a tiempo.",
    "El buen diseño se nota por lo que hace, no por lo que dice.",
]


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def _load_b64(path: Path):
    try:
        if path.is_file():
            return base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        pass
    return ""


def _candidate_dirs():
    root = Path(__file__).resolve().parent.parent
    yield root / "img"
    yield Path.cwd() / "img"
    yield root
    yield Path.cwd()
    yield root / "static"
    yield Path.cwd() / "static"


def _load_logo_b64():
    for d in _candidate_dirs():
        b64 = _load_b64(d / LOGO_FILE)
        if b64:
            return b64
    return ""


def _load_user_photo(display_name="", email="") -> tuple:
    """Devuelve (mime, base64) de la foto del usuario en img/ o ("", "")."""
    tokens = []
    if display_name and display_name.strip():
        tokens.append(_normalize(display_name).split()[0])
    if email and email.strip():
        local = email.split("@")[0].replace(".", " ").replace("_", " ").strip()
        if local:
            tokens.append(_normalize(local).split()[0])
    seen = set()
    for t in tokens:
        if t in seen:
            continue
        seen.add(t)
        name = PHOTO_ALIASES.get(t, t)
        for d in IMG_DIRS:
            for ext, mime in (("jpg", "image/jpeg"), ("jpeg", "image/jpeg"),
                              ("png", "image/png"), ("webp", "image/webp"),
                              ("gif", "image/gif")):
                b64 = _load_b64(d / f"{name}_generated.{ext}")
                if b64:
                    return mime, b64
    return "", ""


def _default_name(display_name, email):
    if display_name and display_name.strip():
        return display_name.strip()
    local = (email or "").split("@")[0].replace(".", " ").replace("_", " ")
    return local.strip().title() or email or ""


def build_default_signature(display_name, email, phone=""):
    base = _default_name(display_name, email)
    name = NAME_OVERRIDES.get(_normalize(base), base)
    phone_html = (
        f"<div style=\"color:#555555;\">Tel. {phone}</div>" if phone else ""
    )
    photo_mime, photo_b64 = _load_user_photo(name, email)
    logo = _load_logo_b64()
    photo_html = (
        f'<img src="data:{photo_mime};base64,{photo_b64}" width="110" '
        'style="max-width:110px;height:auto;border:0;border-radius:6px;display:block;" alt="" />'
        if photo_b64
        else ""
    )
    img_html = (
        f'<img src="data:image/png;base64,{logo}" width="200" '
        'style="max-width:200px;height:auto;border:0;" alt="ECCSA Automation" />'
        if logo
        else ""
    )
    photo_td = (
        f'<td style="vertical-align:middle;padding-right:16px;">{photo_html}</td>'
        if photo_html
        else ""
    )
    phrase = random.choice(PHRASES)
    return f"""\
<table cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;font-family:Arial,'Helvetica Neue',Helvetica,sans-serif;color:#3a3a3a;font-size:13px;line-height:1.5;border-top:3px solid #0B5394;margin:12px 0 0;padding-top:12px;">
  <tr>
    {photo_td}
    <td style="vertical-align:middle;padding-right:16px;">
      <div style="font-size:15px;font-weight:bold;color:#0B5394;">{name}</div>
      {phone_html}
      <div style="color:#555555;">{email}</div>
      <div style="height:8px;font-size:0;line-height:0;">&nbsp;</div>
      <div style="font-weight:bold;color:#0B5394;">ECCSA Automation</div>
      <div style="color:#555555;">www.ecc-sa.com.mx</div>
      <div style="color:#555555;">Fray Luis de Le&oacute;n 1713 &middot; Jard&iacute;n Espa&ntilde;ol</div>
      <div style="color:#555555;">Monterrey, Nuevo Le&oacute;n &middot; C.P. 64820 &middot; M&eacute;xico</div>
      <div style="height:8px;font-size:0;line-height:0;">&nbsp;</div>
      <div style="color:#888888;font-style:italic;font-size:12px;">&laquo;{phrase}&raquo;</div>
    </td>
    <td style="vertical-align:middle;">{img_html}</td>
  </tr>
</table>"""