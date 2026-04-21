"""AI 辯論擂台主程式：PTT 挑題 → 多人格辯論 → 裁判評論 → 產出靜態網站。"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from utils.aws_auth import setup_aws_session
from .debate import load_prompt, run_debate
from .personas import by_id, pick_random
from .render import generate_website
from .topic_picker import collect_candidates, load_topic_picker_prompt, pick_topic

logging.basicConfig(format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).parent.parent
TIMEOUT_SECONDS = 900


def _timeout_handler(_signum, _frame):
    raise TimeoutError(f"整支程式執行超過 {TIMEOUT_SECONDS // 60} 分鐘，已中止")


def load_config() -> dict:
    with open(PROJECT_DIR / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI 辯論擂台每日產生器")
    parser.add_argument("--profile", default=None, help="AWS profile name")
    parser.add_argument("--region", default=None, help="覆蓋 AWS region")
    parser.add_argument("--seed", type=int, default=None, help="隨機抽人格的種子（debug 用）")
    parser.add_argument("--personas", default=None,
                        help="手動指定人格 ID，以逗號分隔（跳過隨機抽選）")
    parser.add_argument("--topic", default=None,
                        help="手動指定辯論題目（跳過 PTT 抓取）")
    parser.add_argument("--render-only", action="store_true",
                        help="只重新渲染網頁，不執行辯論")
    return parser.parse_args()


def _resolve_personas(args, n: int):
    if args.personas:
        ids = [s.strip() for s in args.personas.split(",") if s.strip()]
        personas = [by_id(i) for i in ids]
        if any(p is None for p in personas):
            invalid = [i for i, p in zip(ids, personas) if p is None]
            raise ValueError(f"未知的人格 ID：{invalid}")
        return personas
    return pick_random(n, seed=args.seed)


def main() -> int:
    start = time.perf_counter()
    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(TIMEOUT_SECONDS)

    try:
        args = parse_args()
        config = load_config()

        prompts_dir = PROJECT_DIR / config["debate"]["system_prompt_dir"]
        data_dir = PROJECT_DIR / config["output"]["data_dir"]
        docs_dir = PROJECT_DIR / config["output"]["docs_dir"]
        giscus_cfg = config.get("giscus", {"enabled": False})

        if args.render_only:
            print("[僅渲染模式] 重新生成靜態網站 ...")
            n = generate_website(data_dir, docs_dir, giscus_cfg, keep_n=config["output"]["keep_n"])
            print(f"      已產生 {n} 份辯論頁至 {docs_dir}")
            return 0

        default_region = config["aws"]["default_region"]
        bedrock_model = config["aws"]["bedrock_model"]
        profile = args.profile or (
            None if os.getenv("AWS_ACCESS_KEY_ID") else config["aws"].get("default_profile")
        )
        if profile:
            print(f"[*] 使用 AWS profile: {profile}")
        aws_region = setup_aws_session(profile, args.region, default_region)

        tw_now = datetime.now(ZoneInfo("Asia/Taipei"))
        report_date = tw_now.strftime("%Y-%m-%d")

        # --- 1. 挑題 ---
        print(f"[1/4] 挑選 {report_date} 辯論題目 ...")
        if args.topic:
            topic = {
                "debate_topic": args.topic,
                "topic_description": "（手動指定）",
                "reason": "manual",
                "source": {},
                "source_content": "",
            }
            print(f"      手動題目：{args.topic}")
        else:
            candidates = collect_candidates(
                boards=config["ptt"]["boards"],
                top_n_per_board=config["ptt"]["top_n_per_board"],
                min_push_count=config["ptt"]["min_push_count"],
                pages_per_board=config["ptt"].get("pages_per_board", 3),
            )
            if not candidates:
                print("      無符合條件的候選文章，今日跳過")
                return 0
            picker_prompt = load_topic_picker_prompt(prompts_dir)
            topic = pick_topic(
                candidates, aws_region, bedrock_model,
                config["claude"]["topic_picker_max_tokens"], picker_prompt,
            )
            if not topic:
                print("      Claude 判定無合適題目，今日跳過")
                return 0
            print(f"      ✓ 題目：{topic['debate_topic']}")

        # --- 2. 抽人格 ---
        print(f"[2/4] 抽選辯論人格 ...")
        personas = _resolve_personas(args, config["debate"]["persona_count"])
        for p in personas:
            print(f"      {p.emoji} {p.name}")

        # --- 3. 辯論 ---
        print(f"[3/4] 開始辯論（{config['debate']['rounds']} 輪）...")
        debater_prompt = load_prompt(prompts_dir, "debater")
        judge_prompt = load_prompt(prompts_dir, "judge")
        debate = run_debate(
            topic=topic,
            personas=personas,
            rounds=config["debate"]["rounds"],
            aws_region=aws_region,
            bedrock_model=bedrock_model,
            max_tokens=config["claude"]["max_tokens"],
            judge_max_tokens=config["claude"]["judge_max_tokens"],
            debater_system=debater_prompt,
            judge_system=judge_prompt,
        )

        # 寫入 JSON 紀錄
        data_dir.mkdir(parents=True, exist_ok=True)
        out_path = data_dir / f"debate_{report_date}.json"
        out_path.write_text(json.dumps(debate, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"      已寫入：{out_path}")

        # --- 4. 渲染網站 ---
        print(f"[4/4] 更新靜態網站 ...")
        n = generate_website(data_dir, docs_dir, giscus_cfg, keep_n=config["output"]["keep_n"])
        print(f"      已產生 {n} 份辯論頁至 {docs_dir}")
        return 0

    except (ValueError, TimeoutError) as e:
        logger.error("%s", e)
        return 1
    finally:
        signal.alarm(0)
        elapsed = time.perf_counter() - start
        print(f"[*] 總執行時間：{elapsed:.2f} 秒")


if __name__ == "__main__":
    sys.exit(main())
