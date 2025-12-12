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
import httpx


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.playwright = await async_playwright().start()
    app.state.browser = await app.state.playwright.chromium.launch(headless=True)
    app.state.page = await app.state.browser.new_page()
    app.state.gemini = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    app.state.prev_submit = None
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
    raw = re.sub(r"<[^>]+>", "", raw)
    raw = raw.replace("...", "null")
    raw = re.sub(r",\s*([}\]])", r"\1", raw)
    return raw.strip()


async def extract_everything(page: Page, url: str):
    """Load a quiz URL and extract all data for LLM."""

    await page.goto(url, wait_until="networkidle")

    try:
        page_text = await page.inner_text("body")
    except:
        page_text = ""

    try:
        html = await page.content()
    except:
        html = ""

    payload_templates = []
    blocks = await page.query_selector_all("pre, code")

    for block in blocks:
        raw = (await block.inner_text()).strip()
        try:
            payload_templates.append(json.loads(raw))
            continue
        except:
            pass

        cleaned = clean_json_text(raw)
        try:
            payload_templates.append(json.loads(cleaned))
        except:
            pass

    submit_url = None

    for payload in payload_templates:
        if not isinstance(payload, dict):
            continue
        for key, value in payload.items():
            if isinstance(value, str):
                full_url = urljoin(page.url, value)
                if "submit" in full_url.lower():
                    submit_url = full_url
                    app.state.prev_submit = submit_url
                    break
                else:
                    submit_url = app.state.prev_submit

    url_pattern = r"(https?://[^\s\"'<>()]+|/[^\s\"'<>()]+)"

    if not submit_url:
        urls = re.findall(url_pattern, page_text)
        for u in urls:
            full = urljoin(page.url, u)
            if "submit" in full.lower():
                submit_url = full
                app.state.prev_submit = submit_url
                break
            else:
                submit_url = app.state.prev_submit

    if not submit_url:
        urls = re.findall(url_pattern, html)
        for u in urls:
            full = urljoin(page.url, u)
            if "submit" in full.lower():
                submit_url = full
                app.state.prev_submit = submit_url
                break
            else:
                submit_url = app.state.prev_submit

    hrefs = []
    a_tags = await page.query_selector_all("a")

    for a in a_tags:
        href = await a.get_attribute("href")
        if href:
            hrefs.append(urljoin(page.url, href))

    linked_pages = {}
    for h in hrefs:
        if not h.startswith("http"):
            continue
        if page.url.split("//")[1].split("/")[0] not in h:
            continue

        try:
            await page.goto(h, wait_until="networkidle")
            l_html = await page.content()
            l_text = await page.inner_text("body")
            linked_pages[h] = {"html": l_html, "text": l_text}
        except:
            pass

    await page.goto(url, wait_until="networkidle")

    pdfs, csvs, audios, images = [], [], [], []

    for h in hrefs:
        if h.endswith(".pdf"):
            pdfs.append(h)
        elif h.endswith(".csv"):
            csvs.append(h)
        elif any(h.endswith(ext) for ext in [".mp3", ".opus", ".wav"]):
            audios.append(h)
        elif any(h.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif"]):
            images.append(h)

    audio_tags = await page.query_selector_all("audio")
    for audio in audio_tags:
        src = await audio.get_attribute("src")
        if src:
            audios.append(urljoin(page.url, src))

    img_tags = await page.query_selector_all("img")
    img_links = []

    for img in img_tags:
        src = await img.get_attribute("src")
        if not src:
            continue
        if src.startswith("data:image"):
            img_links.append(src)
        else:
            img_links.append(urljoin(page.url, src))

    bg_urls = re.findall(r'url\((.*?)\)', html)
    for bg in bg_urls:
        bg = bg.strip('\'"')
        img_links.append(urljoin(page.url, bg))

    script_tags = await page.query_selector_all("script:not([src])")
    js_scripts = []

    for tag in script_tags:
        try:
            content = await tag.inner_html()
            js_scripts.append(content)
        except:
            pass

    return {
        "current_url": page.url,
        "page_text": page_text,
        "html": html,
        "payload_templates": payload_templates,
        "submit_url": submit_url,
        "pdf_links": pdfs,
        "csv_links": csvs,
        "audio_links": audios,
        "image_links": images + img_links,
        "linked_pages": linked_pages,
        "js_scripts": js_scripts,
    }


async def call_llm(extracted: dict, app: FastAPI):

    prompt = f"""You are an expert data scientist who can solve quizzes given in any webpage as quickly as possible
This is the url of the current page: {extracted['current_url']}
This is the content of the web page: {extracted['page_text']}

IMPORTANT
    -Always return ONLY a JSON object in code execution output like:
        {{
            "email": "23f2004661@ds.study.iitm.ac.in",
            "secret": "toothless",
            "url": "{extracted['current_url']}",
            "answer": 12345
        }}
"""
    contents = [prompt]

    async with httpx.AsyncClient() as client:

        for link in extracted["csv_links"]:
            try:
                resp = await client.get(link)
                contents.append(types.Part.from_bytes(resp.content, "text/csv"))

            except:
                pass

        for link in extracted["pdf_links"]:
            try:
                resp = await client.get(link)
                contents.append(types.Part.from_bytes(resp.content, "application/pdf"))
            except:
                pass

        def guess_audio_mime(url: str):
            return (
                "audio/mpeg" if url.endswith(".mp3") else
                "audio/wav" if url.endswith(".wav") else
                "audio/ogg; codecs=opus" if url.endswith(".opus") else
                "application/octet-stream"
            )

        for link in extracted["audio_links"]:
            try:
                resp = await client.get(link)
                contents.append(types.Part.from_bytes(resp.content, guess_audio_mime(link)))
            except:
                pass

        for link in extracted["image_links"]:
            try:
                resp = await client.get(link)
                ext = link.lower()

                if ext.endswith(".png"):
                    mime = "image/png"
                elif ext.endswith(".jpg") or ext.endswith(".jpeg"):
                    mime = "image/jpeg"
                elif ext.endswith(".gif"):
                    mime = "image/gif"
                elif ext.endswith(".webp"):
                    mime = "image/webp"
                elif ext.endswith(".svg"):
                    mime = "image/svg+xml"
                else:
                    mime = "application/octet-stream"

                contents.append(
                    types.Part.from_bytes(
                        data=resp.content,
                        mime_type=mime
                    )
                )
            except Exception as e:
                print("Image attach failed:", e)

    def extract_json(text: str):
        if not text:
            return None
        text = re.sub(r"```[\w]*", "", text).replace("```", "")
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except:
            return None
    try:
        client = app.state.gemini
        await asyncio.sleep(3) # delay here
        response = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=contents,
            config=types.GenerateContentConfig(
                tools=[
                    types.Tool(code_execution=types.ToolCodeExecution),
                    {"url_context": {}},
                    {"google_search": {}}
                ]
            )
        )

        final_json = None

        if response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:

                if getattr(part, "text", None):
                    j = extract_json(part.text)
                    if j:
                        final_json = j

                if getattr(part, "code_execution_result", None):
                    output = part.code_execution_result.output
                    j = extract_json(output)
                    if j:
                        final_json = j

                if getattr(part, "executable_code", None):
                    code = part.executable_code.code
                    print(f"this is the script made by LLM:\n{code}")
                    j = extract_json(code)
                    if j:
                        final_json = j

        if not final_json:
            print("⚠️ No valid JSON detected. Using fallback.")
            final_json = {
                "email": extracted.get("email", "23f2004661@ds.study.iitm.ac.in"),
                "secret": extracted.get("secret", "toothless"),
                "url": extracted["current_url"],
                "answer": "unknown"
            }

        submit_url = extracted.get("submit_url") or app.state.prev_submit

        return [submit_url, final_json]
    except Exception as e:
        print(e)
        final_json = {
            "email": extracted.get("email", "23f2004661@ds.study.iitm.ac.in"),
            "secret": extracted.get("secret", "toothless"),
            "url": extracted["current_url"],
            "answer": "unknown"
        }
        submit_url = extracted.get("submit_url") or app.state.prev_submit
        return [submit_url,final_json]


async def submit_answer(app: FastAPI, submit_url: str, payload: dict):
    print("📤 SUBMITTING ANSWER TO:", submit_url)
    print("📦 PAYLOAD:", payload)

    async with httpx.AsyncClient() as client:
        resp = await client.post(submit_url, json=payload)

    print("📥 SUBMISSION RESPONSE:", resp.text)

    try:
        result = resp.json()
    except:
        print("❌ Could not decode JSON")
        return

    if result.get("url"):
        next_url = result["url"]
        print("➡️ NEXT QUIZ URL:", next_url)
        await solve_quiz_chain(app.state.page, next_url)
    else:
        print("🏁 QUIZ ENDED")


async def solve_quiz_step(page: Page, url: str):
    print(f"Solving quiz step at {url}")
    extracted = await extract_everything(page, url)
    print("Extracted:", extracted)
    llm_output = await call_llm(extracted, app)
    print("LLM output received:", llm_output)
    submit_url, payload = llm_output
    await submit_answer(app, submit_url, payload)


async def solve_quiz_chain(page: Page, start_url: str):
    print("Starting quiz solving chain")
    await solve_quiz_step(page, start_url)


@app.post("/task")
async def handle_task(data: dict, background_tasks: BackgroundTasks):
    secret = os.getenv("SECRET")
    print(data)
    if data.get("secret") == secret:
        app.state.user_email = data["email"]
        app.state.user_secret = data["secret"]
        background_tasks.add_task(solve_quiz_chain, app.state.page, data['url'])
        return {"message": "Secret Matches!", "status_code": 200}
    else:
        return {"message": "Secret does not match", "status_code": 403}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=8000)
