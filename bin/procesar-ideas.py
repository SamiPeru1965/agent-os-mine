#!/usr/bin/env python3
"""Notion -> Agent OS: clasifica ideas nuevas de la BD Ideas con el Concilio completo (consejo.py)."""
import os, sys, json, re, datetime, pathlib, unicodedata, urllib.request, urllib.error, subprocess, time, tempfile

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DB = os.environ.get("NOTION_IDEAS_DB")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
NOTION_VERSION = "2022-06-28"
VAULT = pathlib.Path.home() / "obsidian-agentos/Shared/ideas"
CONSEJO = pathlib.Path.home() / "agent-os/bin/consejo.py"
# ponytail: el wrapper corta a los 300s y cada concilio puede tardar hasta 120s; el resto queda para el siguiente cron
MAX_IDEAS_POR_CORRIDA = 2
DEDUP_MODELO = "anthropic/claude-haiku-4.5"
DEDUP_UMBRAL = 0.8

sys.path.insert(0, str(CONSEJO.parent))
from consejo import _post, _transitorio  # noqa: E402

TIPOS = {"feature", "bug", "tarea", "pregunta", "proyecto"}
VERTICALES = {"SmartCont", "Charlie House", "BeautyAppoint", "SuperSeller", "YouTube", "Print", "Aprender", "Cross"}
ESFUERZOS = {"S", "M", "L", "XL"}


def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def notion_request(method, path, body=None):
    req = urllib.request.Request(
        f"https://api.notion.com/v1{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def query_ideas_nuevas():
    body = {"filter": {"property": "Estado", "select": {"equals": "🌱 nueva"}},
            "sorts": [{"timestamp": "created_time", "direction": "ascending"}]}
    data = notion_request("POST", f"/databases/{NOTION_DB}/query", body)
    return data.get("results", [])


def extraer_idea(page):
    props = page["properties"]
    idea = "".join(t["plain_text"] for t in props["Idea"]["title"])
    detalle_rt = props.get("Detalle", {}).get("rich_text", [])
    detalle = "".join(t["plain_text"] for t in detalle_rt)
    return idea.strip(), detalle.strip()


def armar_prompt(idea, detalle):
    # La idea va primero: consejo.py arma el nombre del acta con los primeros 50 chars del prompt
    return f"""Idea: {idea}
Detalle: {detalle or "sin detalle adicional"}
Fecha de hoy: {datetime.date.today().isoformat()} (úsala para razonar sobre plazos y ventanas de tiempo)

Eres el Concilio del Agent OS de Saul, entrepreneur peruano construyendo Imperio Digital (agencia multi-vertical de automatización con IA). Analiza la idea capturada de arriba.

Guía de verticales: SmartCont = contabilidad automatizada; Charlie House = hospitality/hoteles; BeautyAppoint = spa/belleza; SuperSeller = ventas/soporte; YouTube = canal de shorts virales; Print = web-to-print de tarjetas; Aprender = aprendizaje personal; Cross = transversal o no encaja en ninguna.

Evalúala desde 3 perspectivas: viabilidad técnica, encaje estratégico, y prioridad relativa. El árbitro debe integrar las 3 perspectivas y devolver AL FINAL de su síntesis, en un bloque separado, este JSON EXACTO (sin ```json, sin texto extra después del cierre):

{{
  "tipo": "feature | bug | tarea | pregunta | proyecto",
  "vertical": "SmartCont | Charlie House | BeautyAppoint | SuperSeller | YouTube | Print | Aprender | Cross",
  "esfuerzo": "S | M | L | XL",
  "recomendacion": "1-2 frases con acción concreta recomendada"
}}

El resto de la síntesis (puntos de acuerdo, divergencias, análisis) queda como texto libre ANTES del JSON."""


def llamar_concilio(idea, detalle):
    try:
        r = subprocess.run(["python3", str(CONSEJO), armar_prompt(idea, detalle)],
                           capture_output=True, text=True, timeout=120, check=False)
    except subprocess.TimeoutExpired:
        raise RuntimeError("consejo.py timeout (120s)")
    if r.returncode != 0:
        raise RuntimeError(f"consejo.py exit={r.returncode}: {r.stderr.strip()[-300:]}")
    lineas = r.stdout.strip().splitlines()
    acta = pathlib.Path(lineas[-1]) if lineas else None
    if not acta or not acta.is_file():
        raise RuntimeError(f"consejo.py no devolvió una ruta de acta válida: {r.stdout.strip()[-200:]!r}")
    return acta


def parsear_acta(texto):
    """Devuelve (clasificacion, sintesis_sin_json). Lanza ValueError si algo falta."""
    m = re.search(r"^## Síntesis del árbitro[^\n]*\n(.*?)(?=^## Drafts individuales|\Z)", texto, re.S | re.M)
    if not m:
        raise ValueError("acta sin sección '## Síntesis del árbitro'")
    sintesis = m.group(1)
    bloques = list(re.finditer(r'\{[^{}]*"tipo"[^{}]*\}', sintesis))
    if not bloques:
        raise ValueError("síntesis sin bloque JSON de clasificación")
    ultimo = bloques[-1]
    try:
        d = json.loads(ultimo.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON roto ({e})")
    faltan = [k for k in ("tipo", "vertical", "esfuerzo", "recomendacion") if not str(d.get(k, "")).strip()]
    if faltan:
        raise ValueError(f"faltan campos: {faltan}")
    if d["tipo"] not in TIPOS or d["vertical"] not in VERTICALES or d["esfuerzo"] not in ESFUERZOS:
        raise ValueError(f"clasificación fuera de rango: {d}")
    antes = sintesis[:ultimo.start()]
    antes = re.sub(r"```(json)?\s*$", "", antes.rstrip())      # fence abierto antes del JSON
    antes = re.sub(r"(\n\s*-{3,}\s*)+$", "", antes.rstrip())    # separadores sueltos al final
    return d, antes.strip()


def rich_text(texto):
    # Notion: máx 2000 chars por objeto de texto, 100 objetos por propiedad
    return [{"text": {"content": texto[i:i + 2000]}} for i in range(0, min(len(texto), 200000), 2000)]


def actualizar_notion(page_id, clasificacion, sintesis, fecha_iso):
    body = {
        "properties": {
            "Estado": {"select": {"name": "📋 clasificada"}},
            "Tipo": {"select": {"name": clasificacion["tipo"]}},
            "Vertical": {"select": {"name": clasificacion["vertical"]}},
            "Esfuerzo": {"select": {"name": clasificacion["esfuerzo"]}},
            "Análisis": {"rich_text": rich_text(sintesis)},
            "Accion Tomada": {"rich_text": rich_text(clasificacion["recomendacion"])},
            "Procesada": {"date": {"start": fecha_iso}},
        }
    }
    notion_request("PATCH", f"/pages/{page_id}", body)


def slugify(idea):
    s = unicodedata.normalize("NFKD", idea).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:50].strip("-")


def escribir_vault(idea, detalle, clasificacion, sintesis, acta, page_id, capturada, fecha_iso):
    VAULT.mkdir(parents=True, exist_ok=True)
    slug = slugify(idea) or "idea"
    base = f"{fecha_iso}-{slug}"
    path = VAULT / f"{base}.md"
    n = 2
    while path.exists():
        path = VAULT / f"{base}-{n}.md"
        n += 1

    idea_yaml = idea.replace('"', '\\"')
    detalle_yaml = detalle.replace('"', '\\"')
    path.write_text(f"""---
idea: "{idea_yaml}"
detalle: "{detalle_yaml}"
tipo: {clasificacion['tipo']}
vertical: {clasificacion['vertical']}
esfuerzo: {clasificacion['esfuerzo']}
capturada: {capturada}
procesada: {fecha_iso}
notion_id: {page_id}
concilio_acta: "../consejos/{acta.name}"
---

# {idea}

## Detalle
{detalle or "(sin detalle)"}

## Recomendación
{clasificacion['recomendacion']}

## Síntesis del Concilio
{sintesis}

## Acta completa
[[{acta.stem}]] — 3 perspectivas + debate completo
""")
    return path


def leer_frontmatter(texto):
    """Frontmatter YAML plano (clave: valor) sin librería; mismo patrón que actividad.ts."""
    m = re.match(r"---\n(.*?)\n---", texto, re.S)
    if not m:
        return {}
    fm = {}
    for linea in m.group(1).splitlines():
        if ":" not in linea:
            continue
        k, v = linea.split(":", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] == '"':
            v = v[1:-1].replace('\\"', '"')
        fm[k.strip()] = v
    return fm


def cargar_ideas_previas(limite=20, carpeta=VAULT):
    if not carpeta.is_dir():
        return []
    archivos = sorted(carpeta.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    previas = []
    for p in archivos:
        if len(previas) >= limite:
            break
        fm = leer_frontmatter(p.read_text(errors="replace"))
        if not fm.get("idea"):
            continue
        fecha = fm.get("procesada") or fm.get("capturada") or \
            datetime.date.fromtimestamp(p.stat().st_mtime).isoformat()
        previas.append({"slug": p.stem, "idea": fm["idea"], "tipo": fm.get("tipo", ""),
                        "vertical": fm.get("vertical", ""), "esfuerzo": fm.get("esfuerzo", ""),
                        "fecha": fecha})
    return previas


def _parsear_dup(texto):
    """dict validado o None si la respuesta no sirve (ante duda, no bloquea)."""
    m = re.search(r"\{.*\}", texto, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict) or not {"es_dup", "dup_slug", "confianza"} <= d.keys():
        return None
    c = d["confianza"]
    if not isinstance(d["es_dup"], bool) or isinstance(c, bool) or not isinstance(c, (int, float)) or not 0 <= c <= 1:
        return None
    if d["dup_slug"] is not None and not isinstance(d["dup_slug"], str):
        return None
    if d["dup_slug"]:
        d["dup_slug"] = d["dup_slug"].strip().removesuffix(".md")
    return d


def verificar_duplicado(idea_nueva, detalle_nuevo, ideas_previas):
    if not ideas_previas:
        return None
    lista = "\n".join(f'{i}. [{p["slug"]}] "{p["idea"]}" ({p["tipo"]}/{p["vertical"]}/{p["esfuerzo"]})'
                      for i, p in enumerate(ideas_previas, 1))
    prompt = f"""Eres un detector de ideas duplicadas en el sistema de captura de Saul (entrepreneur peruano, Imperio Digital).

Idea nueva capturada:
Título: "{idea_nueva}"
Detalle: "{detalle_nuevo or 'sin detalle'}"

Ideas anteriores ya procesadas:
{lista}

Determina si la idea nueva es duplicada semántica (misma intención aunque con palabras distintas) de alguna anterior. NO consideres duplicadas ideas que suenan similar pero son de verticales distintas, ni variaciones sustanciales (ej: "hacer curso Agent OS" vs "hacer tutorial YouTube Agent OS" NO son duplicadas si cambia el formato).

Devuelve SOLO un objeto JSON válido (sin ```json, sin texto extra):
{{
  "es_dup": boolean,
  "dup_slug": slug exacto de la idea anterior más similar (string) o null si es_dup=false,
  "confianza": número 0.0-1.0 (qué tan seguro estás)
}}"""
    # mismo retry que el árbitro en consejo.py: solo errores transitorios, backoff 2s/4s
    razones = []
    for espera in (2, 4, None):
        try:
            texto = _post(DEDUP_MODELO, [{"role": "user", "content": prompt}], 200, temperature=0)
            break
        except Exception as e:
            if espera is None or not _transitorio(e):
                log(f"WARN dedup: fallo llamando a {DEDUP_MODELO} ({e}); sigue al Concilio")
                return None
            razones.append(f"{type(e).__name__}: {e}")
            log(f"dedup falló ({razones[-1]}), reintento en {espera}s...")
            time.sleep(espera)
    if razones:
        n = len(razones)
        log(f"(dedup resuelto tras {n} reintento{'s' if n > 1 else ''} por {'; '.join(dict.fromkeys(razones))})")
    d = _parsear_dup(texto)
    if d is None:
        log(f"WARN dedup: respuesta inválida {texto.strip()[:200]!r}; sigue al Concilio")
    return d


def marcar_duplicada_en_notion(page_id, dup_slug, idea_previa_dict):
    body = {
        "properties": {
            "Estado": {"select": {"name": "🔄 duplicada"}},
            "Análisis": {"rich_text": rich_text(f"Duplicada de [[{dup_slug}]] - {idea_previa_dict['idea']}")},
            "Accion Tomada": {"rich_text": rich_text("No se dispara Concilio. Ver análisis en nota original.")},
            "Procesada": {"date": {"start": idea_previa_dict["fecha"]}},
        }
    }
    try:
        notion_request("PATCH", f"/pages/{page_id}", body)
        return True
    except Exception as e:
        log(f"✗ fallo marcando duplicada en Notion ({e})")
        return False


def selftest():
    acta = """# Consejo: x

## Síntesis del árbitro (Claude Sonnet 4.6 (árbitro))

## Puntos de acuerdo
Todos coinciden.

```json
{"tipo": "feature", "vertical": "SmartCont", "esfuerzo": "M", "recomendacion": "Hacer un piloto."}
```

---

## Drafts individuales

### Haiku
{"tipo": "bug", "vertical": "Print", "esfuerzo": "S", "recomendacion": "no usar"}
"""
    d, s = parsear_acta(acta)
    assert d["tipo"] == "feature" and d["recomendacion"] == "Hacer un piloto.", d
    assert "## Puntos de acuerdo" in s and "Todos coinciden." in s and "{" not in s and "```" not in s, s
    for roto in ("# sin sintesis", acta.replace('"M"', '"XXL"'), acta.replace('"tipo": "feature", ', "")):
        try:
            parsear_acta(roto)
            raise AssertionError(f"debió fallar: {roto[:60]!r}")
        except ValueError:
            pass
    assert len(rich_text("a" * 4500)) == 3

    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        assert cargar_ideas_previas(carpeta=tmp / "no-existe") == []
        (tmp / "2026-01-01-vieja.md").write_text('---\nidea: "dice \\"hola\\""\ntipo: tarea\nvertical: Cross\n'
                                                  'esfuerzo: S\ncapturada: 2026-01-01\n---\n# x\n')
        (tmp / "2026-01-02-nueva.md").write_text('---\nidea: "nueva: con dos puntos"\nprocesada: 2026-01-03\n---\n')
        (tmp / "sin-frontmatter.md").write_text("# nada\n")
        os.utime(tmp / "2026-01-01-vieja.md", (1, 1))
        p = cargar_ideas_previas(carpeta=tmp)
        assert [x["slug"] for x in p] == ["2026-01-02-nueva", "2026-01-01-vieja"], p
        assert p[0]["idea"] == "nueva: con dos puntos" and p[0]["fecha"] == "2026-01-03", p
        assert p[1]["idea"] == 'dice "hola"' and p[1]["fecha"] == "2026-01-01" and p[1]["vertical"] == "Cross", p
        assert len(cargar_ideas_previas(limite=1, carpeta=tmp)) == 1

    ok = _parsear_dup('```json\n{"es_dup": true, "dup_slug": "2026-09-23-x.md", "confianza": 0.9}\n```')
    assert ok == {"es_dup": True, "dup_slug": "2026-09-23-x", "confianza": 0.9}, ok
    assert _parsear_dup('{"es_dup": false, "dup_slug": null, "confianza": 0}')["es_dup"] is False
    for malo in ("nada", "{roto", '{"es_dup": true, "confianza": 0.9}', '{"es_dup": "si", "dup_slug": null, "confianza": 1}',
                 '{"es_dup": true, "dup_slug": "x", "confianza": 1.5}'):
        assert _parsear_dup(malo) is None, malo
    print("selftest OK")


def main():
    if not NOTION_TOKEN or not NOTION_DB or not OPENROUTER_API_KEY:
        log("ERROR: NOTION_TOKEN / NOTION_IDEAS_DB / OPENROUTER_API_KEY faltan en env. Corre: source ~/.config/agent-os/env")
        sys.exit(3)

    try:
        ideas = query_ideas_nuevas()
    except Exception as e:
        log(f"ERROR consultando Notion: {e}")
        sys.exit(2)

    if not ideas:
        print("sin ideas nuevas")
        sys.exit(0)

    log(f"{len(ideas)} idea(s) nueva(s) encontradas")
    if len(ideas) > MAX_IDEAS_POR_CORRIDA:
        log(f"procesando {MAX_IDEAS_POR_CORRIDA}; {len(ideas) - MAX_IDEAS_POR_CORRIDA} quedan para la siguiente corrida")
        ideas = ideas[:MAX_IDEAS_POR_CORRIDA]

    hoy = datetime.date.today().isoformat()
    procesadas = 0
    escritas = 0
    duplicadas = 0
    fallidas = 0

    for page in ideas:
        page_id = page["id"]
        try:
            idea, detalle = extraer_idea(page)
        except Exception as e:
            log(f"✗ [{page_id}] error: no se pudo leer propiedades ({e})")
            fallidas += 1
            continue
        capturada = page.get("created_time", hoy)[:10]

        # Nivel 2: dedup contra el vault antes de gastar en el Concilio.
        # Se recarga en cada vuelta para ver también las notas escritas en esta misma corrida.
        previas = cargar_ideas_previas(limite=20)
        dup = verificar_duplicado(idea, detalle, previas)
        if dup and dup.get("es_dup") and dup.get("confianza", 0) >= DEDUP_UMBRAL:
            slug = dup.get("dup_slug") or ""
            previa = next((p for p in previas if p["slug"] == slug), None)
            if previa:
                if marcar_duplicada_en_notion(page_id, slug, previa):
                    log(f"⊘ [{idea}] duplicada de [{slug}] (confianza {dup['confianza']:.2f})")
                    duplicadas += 1
                else:
                    log(f"✗ [{idea}] error: duplicada de [{slug}] pero no se pudo marcar en Notion; se reintenta en la próxima corrida")
                    fallidas += 1
                continue  # no se llama al Concilio
            log(f"⚠ [{idea}] marcada dup pero slug {slug!r} no encontrado, procesa normal")

        log(f"Consultando al Concilio: {idea!r}")
        try:
            acta = llamar_concilio(idea, detalle)
            clasificacion, sintesis = parsear_acta(acta.read_text())
        except Exception as e:
            log(f"✗ [{idea}] error: {e}")
            fallidas += 1
            continue

        try:
            actualizar_notion(page_id, clasificacion, sintesis, hoy)
        except Exception as e:
            log(f"✗ [{idea}] error: fallo actualizando Notion ({e}) (acta: {acta})")
            fallidas += 1
            continue
        procesadas += 1

        try:
            path = escribir_vault(idea, detalle, clasificacion, sintesis, acta, page_id, capturada, hoy)
            escritas += 1
        except Exception as e:
            log(f"WARN [{idea}]: clasificada en Notion pero falló escritura al vault ({e})")
            path = None

        log(f"✓ [{idea}] → tipo={clasificacion['tipo']} vertical={clasificacion['vertical']} "
            f"esfuerzo={clasificacion['esfuerzo']} (acta: {acta})")
        if path:
            log(f"  nota: {path}")

    print(f"{procesadas} procesadas, {duplicadas} duplicadas (ahorradas), {fallidas} fallaron; {escritas} escritas al vault")

    if escritas > 0:
        try:
            subprocess.run(
                [str(pathlib.Path.home() / "agent-os/bin/vault-committer.sh"), f"ideas procesadas ({escritas} nuevas, con concilio)"],
                timeout=15, check=False,
            )
        except Exception as e:
            log(f"WARN vault-committer falló: {e}")

    sys.exit(0 if procesadas + duplicadas > 0 else 1)


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
