from app.db.database import  SessionLocal
from app.models.article import Article
from app.models.summaries import Summary
from app.ml.summarizer import summarize
def main():
    db = SessionLocal()

    article=db.query(Article).first()
    if article:
        print("Article ID:", article.id)
        print("Title:", article.title)
        print("URL:", article.url)
        print("Content:", article.content)
        print("Summary:", article.summary)
        print("Author:", article.author)
        print("Source:", article.source)
        print("Published Date:", article.published_date)
        print("Scraped Date:", article.scraped_date)
        print("Category:", article.category)
        print("Tags:", article.tags)
        print("Image URL:", article.image_url)
        print("Is Active:", article.is_active)
    else:
        print("No articles found.")


    try:
        summarized=summarize(article.content)
        print("Summarized:", summarized)


    finally:
        db.close()

if __name__ == "__main__":
    main()
