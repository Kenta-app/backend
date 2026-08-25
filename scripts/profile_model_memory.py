from __future__ import annotations

import argparse
import concurrent.futures
import gc
import json
import os
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv

load_dotenv()


SAMPLE_NEWS = (
    "El Congreso debatira esta semana una reforma politica vinculada con el "
    "financiamiento de partidos, la supervision de campanas electorales y la "
    "rendicion de cuentas ante los organismos electorales. Especialistas "
    "consultados senalaron que la medida podria modificar los plazos de "
    "fiscalizacion y los criterios de sancion administrativa. Representantes "
    "de distintas bancadas indicaron que el texto todavia sera revisado en "
    "comisiones antes de llegar al pleno. La propuesta tambien incluye cambios "
    "en la publicacion de informacion financiera, mecanismos de transparencia "
    "y obligaciones para candidatos durante el proceso electoral. "
) * 12


def process_memory_mb() -> float:
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
    except Exception:
        return -1.0


def snapshot(label: str, started_at: float) -> dict:
    gc.collect()
    return {
        "label": label,
        "rss_mb": round(process_memory_mb(), 2),
        "elapsed_sec": round(time.perf_counter() - started_at, 3),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure memory while loading and exercising the ML runtime."
    )
    parser.add_argument("--skip-summarizer", action="store_true")
    parser.add_argument("--summary-runs", type=int, default=1)
    parser.add_argument("--concurrent-summaries", type=int, default=1)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    started_at = time.perf_counter()
    results = [snapshot("process_started", started_at)]

    try:
        from transformers.utils import logging as hf_logging

        hf_logging.disable_progress_bar()
    except Exception:
        pass

    from app.ml.pipeline import news_analysis_pipeline
    from app.ml.summarizer import summarizer_service

    classifier_ready = news_analysis_pipeline.load()
    results.append(
        {
            **snapshot("classifiers_loaded", started_at),
            "classifier_ready": classifier_ready,
            "fake_news_loaded": news_analysis_pipeline.fake_news_classifier.loaded,
            "stance_loaded": news_analysis_pipeline.stance_classifier.loaded,
        }
    )

    if not args.skip_summarizer:
        summarizer_ready = summarizer_service.load()
        results.append(
            {
                **snapshot("summarizer_loaded", started_at),
                "summarizer_ready": summarizer_ready,
                "summarizer_model": summarizer_service.model_name,
                "num_beams": summarizer_service.num_beams,
                "max_concurrent_generations": summarizer_service.max_concurrent_generations,
            }
        )

        def summarize_once(_: int) -> int:
            return len(summarizer_service.summarize(SAMPLE_NEWS))

        for run_index in range(args.summary_runs):
            run_started = time.perf_counter()
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=args.concurrent_summaries
            ) as executor:
                lengths = list(
                    executor.map(
                        summarize_once,
                        range(args.concurrent_summaries),
                    )
                )
            results.append(
                {
                    **snapshot(f"summary_run_{run_index + 1}", started_at),
                    "run_elapsed_sec": round(time.perf_counter() - run_started, 3),
                    "concurrent_summaries": args.concurrent_summaries,
                    "summary_lengths": lengths,
                }
            )

    if args.json:
        print(json.dumps(results, indent=2))
        return

    for item in results:
        print(item)


if __name__ == "__main__":
    main()
