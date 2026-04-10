import os
import re
import time
import smtplib
import feedparser
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
from google import genai

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

FEEDS = {
    "finance": [
        ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
        ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines"),
        ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
        ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
        ("Guardian Business", "https://www.theguardian.com/uk/business/rss"),
        ("Axios", "https://api.axios.com/feed/"),
    ],
    "geopolitics": [
        ("NPR World", "https://feeds.npr.org/1004/rss.xml"),
        ("Foreign Policy", "https://foreignpolicy.com/feed/"),
        ("Deutsche Welle", "https://rss.dw.com/rdf/rss-en-world"),
    ],
    "tech": [
        ("Hacker News", "https://hnrss.org/frontpage"),
        ("TechCrunch", "https://techcrunch.com/feed/"),
        ("The Verge", "https://www.theverge.com/rss/index.xml"),
        ("Wired", "https://www.wired.com/feed/rss"),
    ],
    "human_insights": [
        ("HBR", "https://feeds.hbr.org/harvardbusiness"),
        ("Psychology Today", "https://www.psychologytoday.com/us/front-page/feed"),
        ("The Cut", "https://www.thecut.com/rss/index.xml"),
        ("Big Think", "https://bigthink.com/feed/"),
    ],
    "ai": [
        ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
        ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
        ("Wired AI", "https://www.wired.com/feed/tag/ai/rss"),
        ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/"),
    ],
    "india": [
        ("The Hindu", "https://www.thehindu.com/feeder/default.rss"),
        ("Business Standard", "https://www.business-standard.com/rss/home_page_top_stories.rss"),
        ("Economic Times Tech", "https://economictimes.indiatimes.com/tech/rss.cms"),
    ],
}

ARTICLES_PER_FEED = 5


ARTICLE_MAX_AGE_HOURS = 36  # skip articles older than this


def _entry_is_fresh(entry):
    """Return True if the entry was published within ARTICLE_MAX_AGE_HOURS, or if no date is available."""
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if not published:
        return True  # no date info — include it rather than silently drop
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ARTICLE_MAX_AGE_HOURS)
    pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
    return pub_dt >= cutoff


def fetch_articles():
    all_articles = {}
    for category, feeds in FEEDS.items():
        fresh_articles = []
        fallback_articles = []  # most-recent articles regardless of age
        for source, url in feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:ARTICLES_PER_FEED]:
                    title = entry.get("title", "").strip()
                    summary = entry.get("summary", entry.get("description", "")).strip()
                    summary = re.sub(r"<[^>]+>", "", summary)[:300]
                    if not title:
                        continue
                    item = f"[{source}] {title}: {summary}"
                    if _entry_is_fresh(entry):
                        fresh_articles.append(item)
                    elif len(fallback_articles) < ARTICLES_PER_FEED:
                        fallback_articles.append(item)
            except Exception as e:
                print(f"  Warning: Could not fetch {source} ({url}): {e}")

        # Use fresh articles; fall back to recent ones if the category would be too thin
        if len(fresh_articles) >= 3:
            articles = fresh_articles
        else:
            articles = fresh_articles + fallback_articles
            if fallback_articles:
                print(f"  {category}: only {len(fresh_articles)} fresh — added {len(fallback_articles)} fallback article(s)")

        all_articles[category] = articles
        print(f"  Fetched {len(articles)} articles for {category}")

    # Anthropic Blog — only include if something was published in the last 24 hours
    anthropic_articles = _fetch_anthropic_if_new()
    if anthropic_articles:
        all_articles["ai"].extend(anthropic_articles)
        print(f"  Added {len(anthropic_articles)} new Anthropic Blog article(s)")
    else:
        print("  Anthropic Blog: no new posts today, skipping")

    return all_articles


def _fetch_anthropic_if_new():
    """Return Anthropic Blog articles published in the last 24 hours, or [] if none."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    articles = []
    try:
        feed = feedparser.parse("https://www.anthropic.com/blog/rss")
        for entry in feed.entries[:ARTICLES_PER_FEED]:
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            if published:
                pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                if pub_dt < cutoff:
                    continue  # older than 24 hours — skip
            title = entry.get("title", "").strip()
            summary = entry.get("summary", entry.get("description", "")).strip()
            summary = re.sub(r"<[^>]+>", "", summary)[:300]
            if title:
                articles.append(f"[Anthropic Blog] {title}: {summary}")
    except Exception as e:
        print(f"  Warning: Could not fetch Anthropic Blog: {e}")
    return articles


def build_prompt(articles):
    sections = {
        "finance": "FINANCE",
        "geopolitics": "GEOPOLITICS",
        "india": "INDIA",
        "tech": "TECH",
        "human_insights": "HUMAN INSIGHTS",
        "ai": "AI",
    }

    article_dump = ""
    for category, label in sections.items():
        article_dump += f"\n\n=== {label} ===\n"
        for item in articles.get(category, []):
            article_dump += f"- {item}\n"

    prompt = f"""You are a sharp, witty friend who actually reads the news. Your job is to write a daily digest that is clear, easy to understand, and fun to read — like explaining the news to a smart friend over coffee.

Here are today's articles across six categories:
{article_dump}

Write a digest with exactly these six sections. Use the section headers exactly as shown:

## Money Talk
Cover the most interesting finance and market news. Start each story with a bold one-line headline that tells me what it's about (e.g. **Fed holds rates steady**), then explain it in plain English in 2–3 sentences. Cover 3–5 stories.

## World Lore
Cover the key geopolitics stories. Start each story with a bold one-line headline, then explain what happened, why it matters, and what most people are missing. Cover 3–5 stories.

## Back Home
Cover the most interesting stories from India — politics, economy, business, tech, or anything else worth knowing. Start each story with a bold one-line headline, then explain it simply. Cover 3–5 stories.

## Tech Tea
Cover what's happening in tech. Start each story with a bold one-line headline, then break it down simply — what it is, why it matters. Cover 3–5 stories.

## Human Insights
Cover the most interesting ideas from psychology, behavior, and human potential. Start each story with a bold one-line headline, then explain the key insight in plain, jargon-free language. Cover 2–3 stories.

## AI
Cover the most important AI news and research. Start each story with a bold one-line headline, then explain what's happening and why it matters in simple terms — assume the reader is smart but not a technical expert. Cover 3–5 stories.

Rules:
- Write like you're explaining to a smart friend, not writing a report
- Jargon and buzzwords are fine if they're genuinely useful — just don't hide behind them
- Each story must start with a bold headline so the reader instantly knows what it's about
- Be direct: state the point, then explain it
- Keep it interesting — if something is dry, find the angle that makes it matter
- If something is surprising or important, say so clearly
- Keep total length under 1500 words
"""
    return prompt


def call_gemini(prompt, retries=3, initial_wait=30):
    client = genai.Client(api_key=GEMINI_API_KEY)
    primary_model = "gemini-2.5-flash"
    fallback_model = "gemini-2.5-flash-lite"

    for model in [primary_model, fallback_model]:
        wait = initial_wait
        for attempt in range(1, retries + 1):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                )
                if model != primary_model:
                    print(f"  (Used fallback model: {model})")
                return response.text
            except Exception as e:
                is_quota = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
                is_unavailable = "503" in str(e) or "UNAVAILABLE" in str(e)
                if is_unavailable:
                    if attempt < retries:
                        print(f"  Model unavailable ({model}). Waiting {wait}s before retry {attempt}/{retries - 1}...")
                        time.sleep(wait)
                        wait *= 2  # exponential backoff: 30s → 60s → 120s
                    else:
                        print(f"  {model} unavailable after all retries.{' Trying fallback model...' if model == primary_model else ''}")
                        break  # move to fallback model
                elif is_quota:
                    if attempt < retries:
                        print(f"  Rate limited. Waiting {wait}s before retry {attempt}/{retries - 1}...")
                        time.sleep(wait)
                        wait *= 2
                    else:
                        print("  Gemini quota exhausted after all retries. Try again after midnight PT.")
                        raise
                else:
                    raise

    raise RuntimeError("All Gemini models failed. Check API status or quota.")


def markdown_to_html_sections(text):
    """Convert the Gemini markdown output into styled HTML blocks."""
    section_styles = {
        "Money Talk": {
            "color": "#00c896",
            "icon": "💰",
            "bg": "#0d2e24",
        },
        "World Lore": {
            "color": "#f0a500",
            "icon": "🌍",
            "bg": "#2e1f00",
        },
        "Tech Tea": {
            "color": "#7b9ef0",
            "icon": "⚡",
            "bg": "#0f1a3a",
        },
        "Human Insights": {
            "color": "#f97316",
            "icon": "🧠",
            "bg": "#2e1500",
        },
        "AI": {
            "color": "#38bdf8",
            "icon": "🤖",
            "bg": "#0a1f2e",
        },
        "Back Home": {
            "color": "#ff9933",
            "icon": "🇮🇳",
            "bg": "#2e1a00",
        },
    }

    # Split by section headers (## Section Name)
    pattern = r"##\s+(Money Talk|World Lore|Back Home|Tech Tea|Human Insights|AI)"
    parts = re.split(pattern, text)

    html_sections = ""

    # parts[0] is any intro text before the first section (usually empty)
    for i in range(1, len(parts), 2):
        section_name = parts[i].strip()
        section_body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        style = section_styles.get(section_name, {"color": "#ffffff", "icon": "•", "bg": "#1a1a2e"})

        # Strip numbered list prefixes (e.g. "1. ") — render as plain paragraphs
        section_body = re.sub(r"^\d+\.\s+", "", section_body, flags=re.MULTILINE)

        # Convert bullet lists
        section_body = re.sub(r"^[-*]\s+(.+)$", r"<li>\1</li>", section_body, flags=re.MULTILINE)

        # Convert **bold**
        section_body = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", section_body)

        # Convert paragraphs
        paragraphs = re.split(r"\n{2,}", section_body)
        body_html = ""
        for p in paragraphs:
            p = p.strip()
            if not p:
                continue
            if p.startswith("<li>") or p.startswith("<ol>"):
                body_html += f"<ol style='padding-left:1.5em;margin:12px 0;'>{p}</ol>"
            else:
                p = p.replace("\n", "<br>")
                body_html += f"<p style='margin:0 0 14px 0;line-height:1.7;'>{p}</p>"

        html_sections += f"""
        <div style="background:{style['bg']};border-left:4px solid {style['color']};
                    border-radius:8px;padding:24px 28px;margin-bottom:24px;">
          <h2 style="color:{style['color']};font-size:1.2rem;font-weight:700;
                     margin:0 0 16px 0;letter-spacing:0.05em;text-transform:uppercase;">
            {style['icon']}&nbsp;&nbsp;{section_name}
          </h2>
          <div style="color:#d0d0d0;font-size:0.95rem;">
            {body_html}
          </div>
        </div>
        """

    return html_sections


def build_html_email(digest_text):
    today = datetime.now().strftime("%A, %B %-d, %Y")
    sections_html = markdown_to_html_sections(digest_text)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Daily Digest</title>
</head>
<body style="margin:0;padding:0;background:#0a0a0f;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0f;padding:32px 16px;">
    <tr>
      <td align="center">
        <table width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%;">

          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);
                       border-radius:12px 12px 0 0;padding:36px 32px;text-align:center;">
              <p style="color:#7b9ef0;font-size:0.75rem;font-weight:600;letter-spacing:0.15em;
                         text-transform:uppercase;margin:0 0 8px 0;">Your Daily Briefing</p>
              <h1 style="color:#ffffff;font-size:2rem;font-weight:800;margin:0 0 8px 0;
                          letter-spacing:-0.02em;">The Digest</h1>
              <p style="color:#8888aa;font-size:0.85rem;margin:0;">{today}</p>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="background:#111118;border-radius:0 0 12px 12px;padding:28px 28px 8px 28px;">
              {sections_html}

              <!-- Footer -->
              <div style="border-top:1px solid #222230;margin-top:8px;padding:20px 0;
                           text-align:center;color:#444460;font-size:0.75rem;">
                Generated by Gemini · Delivered with Python ·
                {datetime.now().strftime("%I:%M %p")}
              </div>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
    return html


def send_email(html_content):
    today = datetime.now().strftime("%b %-d")
    subject = f"The Digest — {today}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = RECIPIENT_EMAIL

    part = MIMEText(html_content, "html")
    msg.attach(part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())

    print(f"  Email sent to {RECIPIENT_EMAIL}")


def main():
    print("=== Daily Digest ===")

    print("\n[1/4] Fetching RSS feeds...")
    articles = fetch_articles()

    print("\n[2/4] Building Gemini prompt...")
    prompt = build_prompt(articles)

    print("[3/4] Calling Gemini API...")
    digest_text = call_gemini(prompt)
    print(f"  Got {len(digest_text)} chars from Gemini")

    print("[4/4] Building HTML and sending email...")
    html = build_html_email(digest_text)
    send_email(html)

    print("\nDone.")


if __name__ == "__main__":
    main()
