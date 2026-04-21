"""Bedrock Claude 呼叫包裝，內建指數退避重試。"""
from __future__ import annotations

import logging
import time

import anthropic

logger = logging.getLogger(__name__)

_RETRYABLE = (
    anthropic.APIError,  # 包含 5xx 與 APIStatusError
    RuntimeError,        # stream 時 "error before message_start" 會拋這個
)


def call_with_retry(
    client: anthropic.AnthropicBedrock,
    *,
    model: str,
    max_tokens: int,
    system: str,
    user: str,
    stream: bool = True,
    retries: int = 4,
) -> tuple[str, int, int]:
    """呼叫 Claude 一次，回傳 (文字, input_tokens, output_tokens)。"""
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            if stream:
                with client.messages.stream(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                ) as s:
                    final = s.get_final_message()
            else:
                final = client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
            text = "".join(b.text for b in final.content if b.type == "text").strip()
            return text, final.usage.input_tokens, final.usage.output_tokens
        except _RETRYABLE as e:
            last_exc = e
            if attempt < retries - 1:
                wait = 2 ** attempt * 3
                logger.warning("Claude 呼叫失敗（%s），%d 秒後重試 ...", type(e).__name__, wait)
                time.sleep(wait)
    raise last_exc  # type: ignore[misc]
