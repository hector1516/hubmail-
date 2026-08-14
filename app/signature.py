import base64
import random
from pathlib import Path

LOGO_FILE = "engrane.png"

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


def _load_logo_b64():
    candidates = [
        Path(__file__).resolve().parent.parent / "static" / LOGO_FILE,
        Path.cwd() / "static" / LOGO_FILE,
    ]
    for p in candidates:
        try:
            if p.is_file():
                return base64.b64encode(p.read_bytes()).decode("ascii")
        except OSError:
            continue
    return ""


def _default_name(display_name, email):
    if display_name and display_name.strip():
        return display_name.strip()
    local = (email or "").split("@")[0].replace(".", " ").replace("_", " ")
    return local.strip().title() or email or ""


def build_default_signature(display_name, email, phone=""):
    name = _default_name(display_name, email)
    phone_html = (
        f"<div style=\"color:#555555;\">Tel. {phone}</div>" if phone else ""
    )
    logo = _load_logo_b64()
    img_html = (
        f'<img src="data:image/png;base64,{logo}" width="110" '
        'style="max-width:110px;height:auto;border:0;" alt="ECCSA Automation" />'
        if logo
        else ""
    )
    phrase = random.choice(PHRASES)
    return f"""\
<table cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;font-family:Arial,'Helvetica Neue',Helvetica,sans-serif;color:#3a3a3a;font-size:13px;line-height:1.5;border-top:3px solid #0B5394;margin:12px 0 0;padding-top:12px;">
  <tr>
    <td style="vertical-align:top;padding-right:16px;">
      <div style="font-size:15px;font-weight:bold;color:#0B5394;">{name}</div>
      {phone_html}
      <div style="color:#555555;">{email}</div>
      <div style="height:10px;font-size:0;line-height:0;">&nbsp;</div>
      <div style="font-weight:bold;color:#0B5394;">ECCSA Automation</div>
      <div style="color:#555555;">www.ecc-sa.com.mx</div>
      <div style="color:#555555;">Fray Luis de Le&oacute;n 1713 &middot; Jard&iacute;n Espa&ntilde;ol</div>
      <div style="color:#555555;">Monterrey, Nuevo Le&oacute;n &middot; C.P. 64820 &middot; M&eacute;xico</div>
      <div style="height:10px;font-size:0;line-height:0;">&nbsp;</div>
      <div style="color:#888888;font-style:italic;font-size:12px;">&laquo;{phrase}&raquo;</div>
    </td>
    <td style="vertical-align:top;">{img_html}</td>
  </tr>
</table>"""
