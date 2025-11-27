from fastapi import FastAPI, BackgroundTasks
import uvicorn
import os
import dotenv
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types
dotenv.load_dotenv()
import subprocess
import traceback
import re
from contextlib import asynccontextmanager
import asyncio
from playwright.async_api import async_playwright, Page
import json
from urllib.parse import urljoin


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.playwright = await async_playwright().start()
    app.state.browser = await app.state.playwright.chromium.launch(headless=True)
    app.state.page = await app.state.browser.new_page()
    print("Browser launched")
    try:
      yield
    finally:
      await app.state.page.close()
      await app.state.browser.close()
      await app.state.playwright.stop()
      print("Browser closed")
    


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def clean_json_text(raw: str) -> str:
    """Clean malformed JSON in <pre> blocks."""
    # Remove HTML tags like <span class="origin">...</span>
    raw = re.sub(r"<[^>]+>", "", raw)

    # Replace invalid ellipsis (...) with null
    raw = raw.replace("...", "null")

    # Remove trailing commas before closing braces
    raw = re.sub(r",\s*([}\]])", r"\1", raw)

    return raw.strip()

async def extract_everything(page: Page, url: str):
    """Load a quiz URL and extract data needed for the LLM."""

    # 1️⃣ Load page (JS-rendered)
    await page.goto(url, wait_until="networkidle")

    # 2️⃣ Extract visible text
    try:
        page_text = await page.inner_text("body")
    except:
        page_text = ""

    # 3️⃣ Extract full rendered HTML
    try:
        html = await page.content()
    except:
        html = ""

    # 4️⃣ Extract JSON payload templates from <pre> or <code>
    payload_templates = []
    blocks = await page.query_selector_all("pre, code")

    for block in blocks:
        raw = (await block.inner_text()).strip()

        # First try: parse as-is
        try:
            payload_templates.append(json.loads(raw))
            continue
        except:
            pass

        # Clean JSON and try again
        cleaned = clean_json_text(raw)
        try:
            payload_templates.append(json.loads(cleaned))
        except:
            pass

    # 5️⃣ Extract submit URL (absolute or relative)
    submit_url = None

    # --- A) From JSON payload ---
    for payload in payload_templates:
        for key, value in payload.items():
            if isinstance(value, str):
                full_url = urljoin(page.url, value)
                if "submit" in full_url.lower():
                    submit_url = full_url
                    break

    # Regex that matches both relative & absolute URLs
    url_pattern = r"(https?://[^\s\"'<>()]+|/[^\s\"'<>()]+)"

    # --- B) From visible text ---
    if not submit_url:
        urls = re.findall(url_pattern, page_text)
        for u in urls:
            full_url = urljoin(page.url, u)
            if "submit" in full_url.lower():
                submit_url = full_url
                break

    # --- C) From HTML ---
    if not submit_url:
        urls = re.findall(url_pattern, html)
        for u in urls:
            full_url = urljoin(page.url, u)
            if "submit" in full_url.lower():
                submit_url = full_url
                break

    # 6️⃣ Extract links: PDF, CSV, audio, images
    pdfs, csvs, audios, images = [], [], [], []
    a_tags = await page.query_selector_all("a")

    for a in a_tags:
        href = await a.get_attribute("href")
        if not href:
            continue

        full_href = urljoin(page.url, href)

        if full_href.endswith(".pdf"):
            pdfs.append(full_href)
        elif full_href.endswith(".csv"):
            csvs.append(full_href)
        elif full_href.endswith(".mp3") or full_href.endswith(".opus") or full_href.endswith(".wav"):
            audios.append(full_href)
        elif any(full_href.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif"]):
            images.append(full_href)

    # 7️⃣ Extract audio from <audio> tags
    audio_tags = await page.query_selector_all("audio")
    for audio in audio_tags:
        src = await audio.get_attribute("src")
        if src:
            audios.append(urljoin(page.url, src))

    return {
        "current_url": page.url,
        "page_text": page_text,
        "html": html,
        "payload_templates": payload_templates,
        "submit_url": submit_url,
        "pdf_links": pdfs,
        "csv_links": csvs,
        "audio_links": audios,
        "image_links": images,
    }

async def solve_quiz_step(page: Page, url: str):
  print(f"Solving quiz step at {url}")
  data  = await extract_everything(page, url)
  print("Extracted data from page")
  print(data)
  


async def solve_quiz_chain(page: Page, start_url: str):
  print("Starting quiz solving chain")
  await solve_quiz_step(page, start_url)  

@app.post("/task")
async def handle_task(data: dict, background_tasks: BackgroundTasks):
  secret=os.getenv("SECRET")
  print(data)
  if data.get("secret")  == secret:
      # Run the task in background (not implemented here)
      background_tasks.add_task(solve_quiz_chain, app.state.page, data['url'])
      return {"message": "Secret Matches!", "status_code": 200}
  else:
      return {"message":"Secret does not match", "status_code": 403}


if __name__ == "__main__":
  import uvicorn
  uvicorn.run(app,port=8000)
      
