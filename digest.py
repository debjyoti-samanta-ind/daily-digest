import os
import time
import smtplib
import feedparser
from datetime import datetime
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
    "creator_economy": [
        ("Digiday", "https://digiday.com/feed/"),
        ("Social Media Today", "https://www.socialmediatoday.com/feeds/all.rss"),
    ],
}

ARTICLES_PER_FEED = 5


def fetch_articles():
    all_articles = {}
    for category, feeds in FEEDS.items():
        articles = []
        for source, url in feeds:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:ARTICLES_PER_FEED]:
                    title = entry.get("title", "").strip()
                    summary = entry.get("summary", entry.get("description", "")).strip()
                    # Strip HTML tags from summary crudely
                    import re
                    summary = re.sub(r"<[^>]+>", "", summary)[:300]
                    if title:
                        articles.append(f"[{source}] {title}: {summary}")
            except Exception as e:
                print(f"  Warning: Could not fetch {source} ({url}): {e}")
        all_articles[category] = articles
        print(f"  Fetched {len(articles)} articles for {category}")
    return all_articles


def build_prompt(articles):
    sections = {
        "finance": "FINANCE",
        "geopolitics": "GEOPOLITICS",
        "tech": "TECH",
        "creator_economy": "CREATOR ECONOMY",
    }

    article_dump = ""
    for category, label in sections.items():
        article_dump += f"\n\n=== {label} ===\n"
        for item in articles.get(category, []):
            article_dump += f"- {item}\n"

    prompt = f"""You are a sharp, witty friend who actually reads the news — think the love child of a Bloomberg terminal and a group chat that's way too online. Your job is to write a daily digest that's informative but fun, punchy but never shallow.

Here are today's articles across four categories:
{article_dump}

Write a digest with exactly these five sections. Use the section headers exactly as shown:

## Money Talk
Recap the most interesting finance/market news. Be sharp, use analogies, make it stick. 3–5 paragraphs.

## World Lore
Cover geopolitics — what's happening, why it matters, what most people are missing. 3–5 paragraphs.

## Tech Tea
Spill on the tech world. What's hype, what's real, what's quietly important. 3–5 paragraphs.

## Creator Szn
Break down what's moving in the creator economy, social media, and digital media. 2–3 paragraphs.

## Speed Round
10 quick one-liner takeaways — one sentence each, punchy and memorable, covering anything from above that didn't make the sections. Format as a numbered list.

Rules:
- Write like you're texting a smart friend, not filing a report
- No corporate speak, no filler, no "it remains to be seen"
- If something is actually wild, say so
- If something is boring but important, make it interesting
- Keep total length under 1200 words
"""
    return prompt


def call_gemini(prompt, retries=2, initial_wait=30):
    client = genai.Client(api_key=GEMINI_API_KEY)
    wait = initial_wait
    for attempt in range(1, retries + 1):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            return response.text
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                if attempt < retries:
                    print(f"  Rate limited. Waiting {wait}s before retry {attempt}/{retries - 1}...")
                    time.sleep(wait)
                    wait *= 2  # exponential backoff: 30s → 60s → 120s → 240s
                else:
                    print("  Gemini quota exhausted after all retries. Try again after midnight PT.")
                    raise
            else:
                raise


def markdown_to_html_sections(text):
    """Convert the Gemini markdown output into styled HTML blocks."""
    import re

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
        "Creator Szn": {
            "color": "#e07af5",
            "icon": "🎨",
            "bg": "#25103a",
        },
        "Speed Round": {
            "color": "#ff6b6b",
            "icon": "🔥",
            "bg": "#3a1010",
        },
    }

    # Split by section headers (## Section Name)
    pattern = r"##\s+(Money Talk|World Lore|Tech Tea|Creator Szn|Speed Round)"
    parts = re.split(pattern, text)

    html_sections = ""

    # parts[0] is any intro text before the first section (usually empty)
    for i in range(1, len(parts), 2):
        section_name = parts[i].strip()
        section_body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        style = section_styles.get(section_name, {"color": "#ffffff", "icon": "•", "bg": "#1a1a2e"})

        # Convert numbered lists
        section_body = re.sub(r"^\d+\.\s+(.+)$", r"<li>\1</li>", section_body, flags=re.MULTILINE)
        if "<li>" in section_body:
            section_body = re.sub(r"(<li>.*?</li>)", r"<ol>\1</ol>", section_body, flags=re.DOTALL)
            section_body = re.sub(r"</ol>\s*<ol>", "", section_body)

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
