from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import date, datetime, time, timedelta

from app.db.database import get_db
from app.models.article import Article
from app.schemas.articlebase import ArticleResponse
from app.scrapers.scrapers import AndinaScraper, ElComercioScraper, LaRepublicaScraper, Peru21Scraper, RPPNoticiasScraper

router = APIRouter()


@router.get("/", response_model=list[ArticleResponse])
def get_articles(db: Session = Depends(get_db)):
    return db.query(Article).order_by(Article.scraped_date.desc()).all()


@router.get("/category/{category}", response_model=list[ArticleResponse])
def get_articles_by_category(
    category: str,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return (
        db.query(Article)
        .filter(Article.category.ilike(category))
        .order_by(Article.scraped_date.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/tag/{tag}", response_model=list[ArticleResponse])
def get_articles_by_tag(
    tag: str,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    like_pattern = f"%{tag}%"
    return (
        db.query(Article)
        .filter(Article.tags.ilike(like_pattern))
        .order_by(Article.scraped_date.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/date/today", response_model=list[ArticleResponse])
def get_articles_today(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    start_of_day = datetime.combine(date.today(), time.min)
    end_of_day = start_of_day + timedelta(days=1)

    return (
        db.query(Article)
        .filter(Article.published_date >= start_of_day)
        .filter(Article.published_date < end_of_day)
        .order_by(Article.published_date.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/latest", response_model=ArticleResponse)
def get_latest_article(db: Session = Depends(get_db)):
    article = db.query(Article).order_by(Article.scraped_date.desc()).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article


@router.get("/{article_id}", response_model=ArticleResponse)
def get_article(article_id: int, db: Session = Depends(get_db)):
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article


@router.get("/test/scraper/{scraper_name}")
def test_scraper(scraper_name: str):
    """Endpoint para probar scrapers individuales"""
    scrapers = {
        "andina": AndinaScraper(),
        "elcomercio": ElComercioScraper(),
        "larepublica": LaRepublicaScraper(),
        "peru21": Peru21Scraper(),
        "rpp": RPPNoticiasScraper(),
    }

    scraper_name = scraper_name.lower()
    if scraper_name not in scrapers:
        raise HTTPException(
            status_code=400,
            detail=f"Scraper no encontrado. Opciones: {', '.join(scrapers.keys())}"
        )

    try:
        scraper = scrapers[scraper_name]
        articles = scraper.scrape()
        return {
            "scraper": scraper_name,
            "articles_count": len(articles),
            "articles": articles
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al ejecutar scraper: {str(e)}")

