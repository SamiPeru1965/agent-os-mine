#!/usr/bin/env python3
"""Concilio: pregunta a 3 modelos vía OpenRouter, sintetiza con un 4to, guarda acta en el vault."""
import os, sys, json, asyncio, datetime, re, pathlib, urllib.request, subprocess

API_URL = "https://openrouter.ai/api/v1/chat/completions"
API_KEY = os.environ.get("OPENROUTER_API_KEY")
VAULT   = pathlib.Path.home() / "obsidian-agentos/Shared/consejos"

CONCILIO = [
    ("Claude Haiku 4.5", "anthropic/claude-haiku-4.5"),
    ("GPT-5 mini",       "openai/gpt-5-mini"),
    ("Gemini 2.5 Flash",       "google/gemini-2.5-flash"),
]
ARBITRO = ("Claude Sonnet 4.6 (árbitro)", "anthropic/claude-sonnet-4.6")

def call_model(model_id, messages, max_tokens=2000):
    body = json.dumps({"model": model_id, "max_tokens": max_tokens, "messages": messages}).encode()
    req = urllib.request.Request(API_URL, data=body, headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/sci/agent-os",
        "X-Title": "Agent OS Concilio",
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[ERROR llamando a {model_id}: {e}]"

async def perspectiva(nombre, model_id, tema):
    loop = asyncio.get_event_loop()
    msg = [{"role": "user", "content": f"Como perspectiva independiente, responde a esta consulta con tu mejor análisis. Sé conciso pero completo (300-600 palabras):\n\n{tema}"}]
    r = await loop.run_in_executor(None, call_model, model_id, msg)
    return nombre, model_id, r

async def main(tema):
    if not API_KEY:
        print("ERROR: OPENROUTER_API_KEY no está en env. Corre: source ~/.config/agent-os/env", file=sys.stderr)
        sys.exit(1)

    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Consultando a {len(CONCILIO)} modelos en paralelo...", file=sys.stderr)
    drafts = await asyncio.gather(*[perspectiva(n, m, tema) for n, m in CONCILIO])

    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Sintetizando con {ARBITRO[0]}...", file=sys.stderr)
    ctx = "\n\n---\n\n".join([f"## Perspectiva {i+1}: {n}\n\n{r}" for i, (n, _, r) in enumerate(drafts)])
    sintesis_prompt = [{"role": "user", "content": f"Eres el árbitro de un concilio de modelos. La pregunta original fue:\n\n>>> {tema} <<<\n\nRecibiste 3 perspectivas independientes:\n\n{ctx}\n\nTu tarea: sintetiza en un veredicto único, señalando (1) los puntos de acuerdo entre las perspectivas, (2) las divergencias significativas y por qué crees que ocurren, (3) tu recomendación final integrada. Sé claro y accionable."}]
    sintesis = call_model(ARBITRO[1], sintesis_prompt, max_tokens=3000)

    fecha = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    slug = re.sub(r'[^a-z0-9]+', '-', tema.lower())[:50].strip('-')
    VAULT.mkdir(parents=True, exist_ok=True)
    acta = VAULT / f"{fecha}-{slug}.md"

    with open(acta, 'w') as f:
        f.write(f"""---
fecha: {datetime.datetime.now().isoformat()}
tema: {tema!r}
modelos: {[m for _, m, _ in drafts]}
arbitro: {ARBITRO[1]}
tipo: consejo
---

# Consejo: {tema}

## Síntesis del árbitro ({ARBITRO[0]})

{sintesis}

---

## Drafts individuales

""")
        for n, m, r in drafts:
            f.write(f"### {n} (`{m}`)\n\n{r}\n\n---\n\n")

    try:
        subprocess.run(
            [str(pathlib.Path.home() / "agent-os/bin/vault-committer.sh"), f"consejo: {tema[:50]}"],
            timeout=15, check=False, capture_output=True
        )
    except Exception:
        pass  # fail-soft, no rompe si vault-committer no está

    print(str(acta))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: consejo.py <tema>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(" ".join(sys.argv[1:])))
