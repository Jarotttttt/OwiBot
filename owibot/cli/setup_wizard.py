"""Interactive `owibot setup` wizard (Hermes-style guided setup)."""
from __future__ import annotations

import getpass
import json
import urllib.request

TIMEOUT = 20


def _get(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data if isinstance(data, dict) else {}


def probe_models(api_base: str) -> list[str]:
    """List model ids from an OpenAI-compatible endpoint. Empty on failure."""
    try:
        data = _get(f"{api_base.rstrip('/')}/models")
        ids = [str(m.get("id", "")).strip() for m in data.get("data", []) if isinstance(m, dict)]
        return [i for i in ids if i]
    except Exception:
        return []


def test_chat(api_base: str, api_key: str, model: str) -> str:
    """Tiny smoke completion. Returns reply text or raises with a short reason."""
    body = {"model": model, "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
            "temperature": 0, "stream": False}
    req = urllib.request.Request(
        f"{api_base.rstrip('/')}/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            msg = json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]
    except Exception as err:
        raise RuntimeError(f"chat test failed: {type(err).__name__}: {str(err)[:160]}")
    text = str(msg.get("content", "") or "").strip()
    if not text and msg.get("tool_calls") is None and "content" not in msg:
        raise RuntimeError("empty reply and no tool calls")
    return text or "(model replied with tool calls only — tool-calling works)"


def check_telegram(token: str) -> str:
    """Validate a bot token via getMe. Returns @username or raises."""
    try:
        data = _get(f"https://api.telegram.org/bot{token.strip()}/getMe")
    except Exception as err:
        raise RuntimeError(f"token check failed: {type(err).__name__}: {str(err)[:120]}")
    if not data.get("ok"):
        raise RuntimeError(f"Telegram rejected the token: {data}")
    return "@" + str(data["result"].get("username", "?"))


def parse_allowlist(raw: str) -> list[str]:
    return [p.lstrip("@") for p in (x.strip() for x in raw.split(",")) if p]


def _ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    try:
        raw = input(f"{prompt}{hint}: ").strip()
    except EOFError:
        print()
        raw = ""
    return raw or default


def _choose(prompt: str, options: list[str]) -> int:
    print(prompt)
    for i, opt in enumerate(options, start=1):
        print(f"  [{i}] {opt}")
    while True:
        raw = _ask(f"Select [1-{len(options)}]", "1")
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        print("Invalid choice, try again.")


def run_wizard(existing: dict) -> dict:
    """Full interactive setup. Returns the new config dict (not yet saved)."""
    from .cli import discover_models
    cfg = dict(existing)
    print("\n=== OwiBot Setup 1/4: LLM provider ===")
    prov = _choose("Where does the model live?", [
        "Auto-detect local (Ollama / LM Studio / Codex)",
        "Custom OpenAI-compatible URL (e.g. http://localhost:20128/v1)",
        "OpenRouter (https://openrouter.ai/api/v1)",
        "OpenAI (https://api.openai.com/v1)",
    ])
    if prov == 0:
        found = discover_models()
        if not found:
            print("No local providers found. Falling back to custom URL.")
            cfg["api_base"] = _ask("API base URL", str(cfg.get("api_base", "http://127.0.0.1:11434/v1")))
        else:
            for i, (base, model, name) in enumerate(found[:15], start=1):
                print(f"  [{i}] {name}: {model} ({base})")
            raw = _ask(f"Select [1-{min(len(found), 15)}]", "1")
            idx = int(raw) - 1 if raw.isdigit() and 1 <= int(raw) <= min(len(found), 15) else 0
            cfg["api_base"], cfg["model"] = found[idx][:2]
    elif prov == 1:
        cfg["api_base"] = _ask("API base URL", str(cfg.get("api_base", "http://127.0.0.1:11434/v1")))
    elif prov == 2:
        cfg["api_base"] = "https://openrouter.ai/api/v1"
    else:
        cfg["api_base"] = "https://api.openai.com/v1"

    key_default = str(cfg.get("api_key", ""))
    if "127.0.0.1" in cfg["api_base"] or "localhost" in cfg["api_base"]:
        cfg["api_key"] = _ask("API key (Enter = none needed locally)", key_default or "local") or "local"
    else:
        try:
            cfg["api_key"] = getpass.getpass("API key: ").strip() or key_default
        except (EOFError, KeyboardInterrupt):
            print()
            cfg["api_key"] = key_default
        if not cfg["api_key"]:
            print("WARNING: empty API key — chat test will likely fail.")

    models = probe_models(cfg["api_base"])
    if models:
        print(f"Found {len(models)} models. First {min(len(models), 12)}:")
        for i, m in enumerate(models[:12], start=1):
            print(f"  [{i}] {m}")
        raw = _ask("Select model number, or type a model id", str(cfg.get("model", models[0])))
        cfg["model"] = models[int(raw) - 1] if raw.isdigit() and 1 <= int(raw) <= len(models[:12]) else raw
    else:
        print("Could not list models from the endpoint.")
        cfg["model"] = _ask("Model id", str(cfg.get("model", "")))

    print("Testing chat completion...")
    try:
        reply = test_chat(cfg["api_base"], cfg["api_key"], cfg["model"])
        print(f"Model replied: {reply[:120]}")
    except RuntimeError as err:
        print(f"{err}\nContinuing anyway — you can fix the model later with /model or re-run setup.")

    print("\n=== OwiBot Setup 2/4: Telegram ===")
    print("Create a bot via @BotFather (/newbot) if you haven't, then paste the token.")
    while True:
        token = _ask("Bot token (or 'skip')", "").strip()
        if token.lower() == "skip" or not token:
            print("Skipping Telegram for now.")
            break
        try:
            who = check_telegram(token)
        except RuntimeError as err:
            print(err)
            continue
        print(f"Connected as {who}. Now find your numeric ID via @userinfobot.")
        allow = _ask("Allowed Telegram IDs/usernames, comma-separated (or * )", "")
        users = parse_allowlist(allow)
        if not users:
            print("Allowlist is required to enable Telegram.")
            continue
        cfg["channels"] = {"telegram": {"token": token, "allow_from": users}}
        break

    print("\n=== OwiBot Setup 3/4: Protection ===")
    mem_cfg = cfg.get("memory") if isinstance(cfg.get("memory"), dict) else {}
    skl_cfg = cfg.get("skills") if isinstance(cfg.get("skills"), dict) else {}
    yn = lambda d: "Y/n" if d else "y/N"
    mem_gate = _ask("Require approval before agent memory saves? [y/N]").lower() in {"y", "yes"}
    skl_gate = _ask("Require approval before agent skill writes? [y/N]").lower() in {"y", "yes"}
    cfg["memory"] = {"write_approval": mem_gate}
    cfg["skills"] = {"write_approval": skl_gate}

    print("\n=== OwiBot Setup 4/4: Summary ===")
    tg = ((cfg.get("channels") or {}).get("telegram") or {})
    print(f"  model: {cfg.get('model')} @ {cfg.get('api_base')}")
    print(f"  telegram: {'configured' if tg.get('token') else 'skipped'}")
    print(f"  gates: memory={mem_gate}, skills={skl_gate}")
    if _ask("Save this config? [Y/n]").lower() in {"", "y", "yes"}:
        return cfg
    raise RuntimeError("Setup cancelled by user.")
