"""辯論主流程：多人格輪流發言 + 裁判評論。"""
from __future__ import annotations

import logging
from pathlib import Path

import anthropic

from .claude_client import call_with_retry
from .personas import Persona

logger = logging.getLogger(__name__)


def _build_debater_user_prompt(
    topic: dict,
    persona: Persona,
    round_idx: int,
    history: list[dict],
) -> str:
    parts = [
        f"## 辯論主題\n{topic['debate_topic']}",
        f"## 背景說明\n{topic.get('topic_description', '（無）')}",
        f"## 你的人格設定\n- 名稱：{persona.name}\n- 風格：{persona.description}\n\n{persona.system_prompt}",
    ]
    if history:
        chunks = []
        for h in history:
            chunks.append(f"【{h['persona_name']}（第 {h['round']} 輪）】\n{h['text']}")
        parts.append("## 前面輪次的發言\n\n" + "\n\n".join(chunks))
    else:
        parts.append("## 前面輪次的發言\n（目前是第一輪，尚無其他人發言）")

    parts.append(
        f"## 本次任務\n這是第 {round_idx} 輪的發言。"
        + ("請亮出你的核心立場。" if round_idx == 1 else "請根據前面的發言做回應並深化你的論點。")
    )
    return "\n\n".join(parts)


def load_prompt(prompts_dir: Path, name: str) -> str:
    return (prompts_dir / f"{name}.md").read_text(encoding="utf-8").strip()


def run_debate(
    topic: dict,
    personas: list[Persona],
    rounds: int,
    aws_region: str,
    bedrock_model: str,
    max_tokens: int,
    judge_max_tokens: int,
    debater_system: str,
    judge_system: str,
) -> dict:
    """執行一場辯論，回傳完整紀錄。"""
    client = anthropic.AnthropicBedrock(aws_region=aws_region)
    history: list[dict] = []
    total_in, total_out = 0, 0

    for r in range(1, rounds + 1):
        for persona in personas:
            print(f"      第 {r} 輪 · {persona.emoji} {persona.name} 發言 ...")
            user = _build_debater_user_prompt(topic, persona, r, history)
            text, t_in, t_out = call_with_retry(
                client, model=bedrock_model, max_tokens=max_tokens,
                system=debater_system, user=user,
            )
            total_in += t_in
            total_out += t_out
            history.append({
                "persona_id": persona.id,
                "persona_name": persona.name,
                "persona_emoji": persona.emoji,
                "persona_color": persona.color,
                "round": r,
                "text": text,
            })

    print("      🧑‍⚖️ 裁判評論 ...")
    debate_transcript = "\n\n".join(
        f"【{h['persona_name']}（第 {h['round']} 輪）】\n{h['text']}"
        for h in history
    )
    judge_user = (
        f"## 辯論主題\n{topic['debate_topic']}\n\n"
        f"## 背景說明\n{topic.get('topic_description', '')}\n\n"
        f"## 辯論紀錄\n{debate_transcript}"
    )
    judge_text, t_in, t_out = call_with_retry(
        client, model=bedrock_model, max_tokens=judge_max_tokens,
        system=judge_system, user=judge_user,
    )
    total_in += t_in
    total_out += t_out

    print(f"      Token 用量：input={total_in}, output={total_out}, total={total_in + total_out}")

    return {
        "topic": topic,
        "personas": [
            {"id": p.id, "name": p.name, "emoji": p.emoji, "color": p.color, "description": p.description}
            for p in personas
        ],
        "rounds": rounds,
        "history": history,
        "judge": judge_text,
        "usage": {
            "input_tokens": total_in,
            "output_tokens": total_out,
            "total_tokens": total_in + total_out,
        },
    }
