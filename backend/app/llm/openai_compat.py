"""Proveedor para APIs compatibles con /chat/completions de OpenAI (DeepSeek, LiteLLM, Ollama, vLLM, OpenAI…).

El historial interno usa bloques tipo Anthropic (text / tool_use / tool_result). Aquí se convierte a mensajes OpenAI
(role system/user/assistant/tool, tool_calls) y la respuesta se convierte de vuelta. Los bloques `thinking` de Claude se
descartan; el `reasoning_content` de DeepSeek se guarda como bloque `reasoning` y se reenvía si pass_reasoning está activo
(DeepSeek devuelve 400 si, con herramientas, se omite el razonamiento de turnos anteriores).
"""
import asyncio
import json
import uuid

import httpx

from .client import LLMResponse, Settings

_transport: httpx.AsyncBaseTransport | None = None  # inyectable en tests
_sleep = asyncio.sleep
RETRY_STATUS = (429, 500, 502, 503, 504)
INVALID_ARGS = "_invalid_arguments"  # centinela: el modelo devolvió argumentos que no son JSON


class LLMError(Exception):
    pass


# ---------------------------------------------------------------- historial interno → OpenAI

def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if b.get("type") == "text")


def to_openai_messages(system: str, messages: list[dict], pass_reasoning: bool) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}]
    for m in messages:
        blocks = m["content"] if isinstance(m["content"], list) else [{"type": "text", "text": m["content"]}]
        if m["role"] == "assistant":
            text = "\n".join(b["text"] for b in blocks if b["type"] == "text")
            calls = [{"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)}}
                     for b in blocks if b["type"] == "tool_use"]
            msg: dict = {"role": "assistant", "content": text or (None if calls else "")}
            if calls:
                msg["tool_calls"] = calls
            if pass_reasoning:
                msg["reasoning_content"] = "\n".join(b["text"] for b in blocks if b["type"] == "reasoning")
            out.append(msg)
        else:
            for b in blocks:
                if b["type"] == "tool_result":
                    prefix = "ERROR: " if b.get("is_error") else ""
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": prefix + _result_text(b.get("content", ""))})
            text = "\n".join(b["text"] for b in blocks if b["type"] == "text")
            if text:
                out.append({"role": "user", "content": text})
    return out


def to_openai_tools(tools: list[dict]) -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""), "parameters": t["input_schema"]}} for t in tools]


# ---------------------------------------------------------------- respuesta OpenAI → bloques internos

_STOP = {"stop": "end_turn", "tool_calls": "tool_use", "function_call": "tool_use", "length": "max_tokens", "content_filter": "refusal"}


def from_openai_response(data: dict, keep_reasoning: bool) -> LLMResponse:
    try:
        choice = data["choices"][0]
        msg = choice["message"]
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"Respuesta inesperada del proveedor: {json.dumps(data)[:300]}") from None
    blocks: list[dict] = []
    if keep_reasoning and msg.get("reasoning_content"):
        blocks.append({"type": "reasoning", "text": msg["reasoning_content"]})
    if msg.get("content"):
        blocks.append({"type": "text", "text": msg["content"]})
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(args, dict):
                raise ValueError
        except ValueError:
            args = {INVALID_ARGS: str(raw)[:500]}
        blocks.append({"type": "tool_use", "id": tc.get("id") or f"call_{uuid.uuid4().hex[:16]}", "name": fn.get("name", ""), "input": args})
    finish = choice.get("finish_reason") or "stop"
    stop = "tool_use" if any(b["type"] == "tool_use" for b in blocks) else _STOP.get(finish, "end_turn")  # algunos backends dicen "stop" con tool_calls
    return LLMResponse(content=blocks, stop_reason=stop, refusal_category="content_filter" if stop == "refusal" else None, usage=data.get("usage") or {})


# ---------------------------------------------------------------- HTTP

def _error_message(status: int, body: str, s: Settings) -> str:
    snippet = " ".join(body.split())[:300]
    if s.api_key:
        snippet = snippet.replace(s.api_key, "***")
    if status in (401, 403):
        return f"{s.provider} rechazó las credenciales (HTTP {status}); revisa la clave de API. {snippet}"
    if status == 404:
        return f"{s.provider}: endpoint o modelo no encontrado (HTTP 404). Revisa AUDIT_LLM_BASE_URL y AUDIT_LLM_MODEL ({s.model}). {snippet}"
    if status == 400:
        return f"{s.provider} rechazó la petición (HTTP 400): {snippet}. Si el modelo no admite herramientas, prueba AUDIT_LLM_TOOLS=0."
    return f"{s.provider} respondió HTTP {status}: {snippet}"


async def create_message(s: Settings, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
    body: dict = {"model": s.model, "messages": to_openai_messages(system, messages, s.pass_reasoning), "max_tokens": s.max_tokens}
    if tools:
        body["tools"] = to_openai_tools(tools)
        body["tool_choice"] = "auto"
    if s.provider == "deepseek":
        body["reasoning_effort"] = s.effort
    body.update(s.extra_body)
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {s.api_key}"} if s.api_key else {})}
    url = f"{s.base_url}/chat/completions"

    last = ""
    async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=15), transport=_transport) as http:
        for attempt in range(3):
            try:
                resp = await http.post(url, headers=headers, json=body)
            except httpx.TransportError as e:
                last = f"no se pudo conectar con {s.host}: {type(e).__name__} {e}".strip()
            else:
                if resp.status_code == 200:
                    try:
                        return from_openai_response(resp.json(), s.pass_reasoning)
                    except ValueError:
                        raise LLMError(f"{s.provider} devolvió una respuesta que no es JSON: {resp.text[:200]}") from None
                last = _error_message(resp.status_code, resp.text, s)
                if resp.status_code not in RETRY_STATUS:
                    raise LLMError(last)
            if attempt < 2:
                await _sleep(1 + 2 * attempt)
    raise LLMError(last)
