"""
Backward-compatible wrapper around the multitask analysis pipeline.

The module name is kept to avoid breaking older imports while the project
transitions from a demo RoBERTa classifier to the real multitask backend.
"""

from app.ml.pipeline import news_analysis_pipeline


def load_model():
    return news_analysis_pipeline.load()


def predict(text: str):
    return news_analysis_pipeline.analyze_news(
        text=text,
        include_summary=False,
    )
