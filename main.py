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

# async def extract_canvas_images(page: Page):
#     """Find all canvas elements and return screenshots as PNG bytes."""
#     canvas_images = []
#     canvas_elements = await page.query_selector_all("canvas")

#     for idx, canvas in enumerate(canvas_elements):
#         try:
#             # Screenshot of just the canvas
#             png_bytes = await canvas.screenshot(type="png")
#             canvas_images.append({
#                 "index": idx,
#                 "bytes": png_bytes,
#                 "mime": "image/png",
#             })
#         except Exception as e:
#             print("Canvas screenshot failed:", e)

#     return canvas_images



async def extract_everything(page: Page, url: str):
    """Load a quiz URL and extract all usable information for the LLM."""

    # --------------------------------------------------------
    # Load Page
    # --------------------------------------------------------
    await page.goto(url, wait_until="networkidle")

    # --------------------------------------------------------
    # Visible text
    # --------------------------------------------------------
    try:
        page_text = await page.inner_text("body")
    except:
        page_text = ""

    # --------------------------------------------------------
    # HTML source
    # --------------------------------------------------------
    try:
        html = await page.content()
    except:
        html = ""

    # --------------------------------------------------------
    # Extract <pre> and <code> JSON
    # --------------------------------------------------------
    payload_templates = []
    blocks = await page.query_selector_all("pre, code")

    for block in blocks:
        raw = (await block.inner_text()).strip()

        # Try raw JSON
        try:
            payload_templates.append(json.loads(raw))
            continue
        except:
            pass

        # Try cleaned JSON
        cleaned = clean_json_text(raw)
        try:
            payload_templates.append(json.loads(cleaned))
        except:
            pass

    # --------------------------------------------------------
    # Submit URL detection (payload → text → html)
    # --------------------------------------------------------
    submit_url = None

    # From payload
    for payload in payload_templates:
        for key, value in payload.items():
            if isinstance(value, str):
                full_url = urljoin(page.url, value)
                if "submit" in full_url.lower():
                    submit_url = full_url
                    break

    # Regex for URL extraction
    url_pattern = r"(https?://[^\s\"'<>()]+|/[^\s\"'<>()]+)"

    # From visible text
    if not submit_url:
        for u in re.findall(url_pattern, page_text):
            full = urljoin(page.url, u)
            if "submit" in full.lower():
                submit_url = full
                break

    # From HTML
    if not submit_url:
        for u in re.findall(url_pattern, html):
            full = urljoin(page.url, u)
            if "submit" in full.lower():
                submit_url = full
                break

    # --------------------------------------------------------
    # Collect all <a href>
    # --------------------------------------------------------
    hrefs = []
    for a in await page.query_selector_all("a"):
        href = await a.get_attribute("href")
        if href:
            hrefs.append(urljoin(page.url, href))

    # --------------------------------------------------------
    # Extract linked pages (safe)
    # --------------------------------------------------------
    linked_pages = {}
    domain = page.url.split("//")[1].split("/")[0]

    for h in hrefs:
        if not h.startswith("http"):
            continue
        if domain not in h:
            continue
        
        try:
            await page.goto(h, wait_until="networkidle")
            l_html = await page.content()
            l_text = await page.inner_text("body")
            linked_pages[h] = {
                "html": l_html,
                "text": l_text,
            }
        except:
            pass

    # Restore
    await page.goto(url, wait_until="networkidle")

    # --------------------------------------------------------
    # File links (PDF, CSV, Audio, Image)
    # --------------------------------------------------------
    pdfs, csvs, audios, images = [], [], [], []

    for h in hrefs:
        h_low = h.lower()

        if h_low.endswith(".pdf"):
            pdfs.append(h)

        elif h_low.endswith(".csv"):
            csvs.append(h)

        elif any(h_low.endswith(ext) for ext in [".mp3", ".opus", ".wav", ".ogg"]):
            audios.append(h)

        elif any(h_low.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"]):
            images.append(h)

    # Extract <audio> tags
    for audio in await page.query_selector_all("audio"):
        src = await audio.get_attribute("src")
        if src:
            audios.append(urljoin(page.url, src))

    # --------------------------------------------------------
    # Extract <img>
    # --------------------------------------------------------
    img_links = []

    for img in await page.query_selector_all("img"):
        src = await img.get_attribute("src")
        if not src:
            continue
        if src.startswith("data:image"):
            img_links.append(src)
        else:
            img_links.append(urljoin(page.url, src))

    # CSS background-image URLs
    bg_urls = re.findall(r'url\((.*?)\)', html)
    for bg in bg_urls:
        bg = bg.strip('"\'')
        img_links.append(urljoin(page.url, bg))

    # --------------------------------------------------------
    # Extract inline JavaScript for LLM reasoning
    # --------------------------------------------------------
    js_scripts = []
    script_tags = await page.query_selector_all("script:not([src])")

    for tag in script_tags:
        try:
            content = await tag.inner_html()
            js_scripts.append(content)
        except:
            pass

    # --------------------------------------------------------
    # Additional semantic context (NEW)
    # --------------------------------------------------------
    # 1. All numbers appearing in the page (useful for puzzles)
    numbers = re.findall(r"-?\d+\.\d+|-?\d+", page_text)

    # 2. Extract key:value pairs (common in quizzes)
    kv_pairs = re.findall(r"([A-Za-z_][A-Za-z0-9_ ]+):\s*([^\n]+)", page_text)

    # 3. Extract JSON-like objects even if malformed
    rough_json_candidates = re.findall(r"\{[^}]+\}", html)

    # --------------------------------------------------------
    # Final return
    # --------------------------------------------------------
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
        "numbers_found": numbers,                   # NEW
        "key_value_pairs": kv_pairs,                # NEW
        "json_candidates": rough_json_candidates,   # NEW
    }


# from tempfile import NamedTemporaryFile

# async def upload_canvas_image(client, item):
#     with NamedTemporaryFile(delete=False, suffix=".png") as tmp:
#         tmp.write(item["bytes"])
#         path = tmp.name

#     uploaded = await client.files.upload(file=path)
#     return uploaded


async def call_llm(extracted: dict, app: FastAPI):

	# ----------------------------------------------------
	# 1. Build the prompt
	# ----------------------------------------------------
	prompt = f"""
You are an expert data scientist who can solve Data Science Quizzes as quickly as possible.

You can get questions like these:
Scraping a website (which may require JavaScript) for information
Sourcing from an API (with API-specific headers provided where required)
Cleansing text / data / PDF / … you retrieved
Processing the data (e.g. data transformation, transcription, vision)
Analysing by filtering, sorting, aggregating, reshaping, or applying statistical / ML models. Includes geo-spatial / network analysis
Visualizing by generating charts (as images or interactive), narratives, slides

Your task is to read the following extracted data from a quiz page, understand the question and instructions, and compute the correct answer.
RULES:
1. Carefully read page_text.
2. Examine payload_templates and fill them CORRECTLY.
3. Use CSV, PDF, AUDIO files if provided.
4. Use linked_pages when scraping is required.
5. Compute the correct exact answer.
6. Fill all fields: email, secret, url, answer.
7. ALWAYS respond via function_call submit_answer.
8. NEVER output plain text.

--- PAGE TEXT ---
{extracted['page_text']}

--- PAYLOAD TEMPLATES ---
{json.dumps(extracted["payload_templates"], indent=2)}

--- SUBMIT URL ---
{extracted["submit_url"]}

--- LINKED PAGES ---
{json.dumps(extracted.get("linked_pages", {}), indent=2)}

--- JS SCRIPTS found on the page---
{json.dumps(extracted.get("js_scripts", []), indent=2)}

The "answer" may need to be a boolean, number, string, base64 URI of a file attachment,
or a JSON object with a combination of these. Your JSON payload must be under 1MB.

--- END OF INPUT DATA ---
"""

	# Gemini "contents" list
	contents = [prompt]

	# ----------------------------------------------------
	# 2. Download ALL files using ONE httpx client
	# ----------------------------------------------------
	async with httpx.AsyncClient() as client:

		# ---- CSVs ----
		for link in extracted["csv_links"]:
			try:
				resp = await client.get(link)
				contents.append(
					types.Part.from_bytes(
						data=resp.content,
						mime_type="text/csv",
					)
				)
			except Exception as e:
				print("CSV attach failed:", e)

		# ---- PDFs ----
		for link in extracted["pdf_links"]:
			try:
				resp = await client.get(link)
				contents.append(
					types.Part.from_bytes(
						data=resp.content,
						mime_type="application/pdf",
					)
				)
			except Exception as e:
				print("PDF attach failed:", e)

		def guess_audio_mime(url: str):
			if url.endswith(".mp3"):
				return "audio/mpeg"
			if url.endswith(".wav"):
				return "audio/wav"
			if url.endswith(".opus"):
				return "audio/ogg; codecs=opus"
			return "application/octet-stream"
		

		# ---- AUDIO ----
		for link in extracted["audio_links"]:
			try:
				resp = await client.get(link)
				mime = guess_audio_mime(link)
				contents.append(
					types.Part.from_bytes(
						data=resp.content,
						mime_type=mime 
					)
				)
			except Exception as e:
				print("Audio attach failed:", e)

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

	# ----------------------------------------------------
	# 3. Define tool schema (function calling)
	# ----------------------------------------------------
	submit_answer_schema = {
		"name": "submit_answer",
		"description": "Submit the solved quiz answer to the evaluator.",
		"parameters": {
			"type": "object",
			"properties": {
				"submit_url": {"type": "string"},
				"payload": {"type": "object"},
			},
			"required": ["submit_url", "payload"]
		},
	}

	tool = types.Tool(function_declarations=[submit_answer_schema])
	config = types.GenerateContentConfig(tools=[tool])
	print(f"This was the content given to LLM:\n{contents}")
	client = app.state.gemini
	
	# for item in extracted["canvas_images"]:
	# 	try:
	# 		uploaded = await upload_canvas_image(client, item)
	# 		contents.append(uploaded)
	# 	except Exception as e:
	# 		print("Canvas upload failed:", e)
	
	# ----------------------------------------------------
	# 4. Call Gemini
	# ----------------------------------------------------
	response = client.models.generate_content(
		model="gemini-2.5-pro",
		contents=contents,
		config=config
	)

	# ----------------------------------------------------
	# 5. Extract the function call
	# ----------------------------------------------------
	for part in response.candidates[0].content.parts:
		if part.text is not None:
			print(part.text)
		if part.executable_code is not None:
			print(part.executable_code.code)
		if part.code_execution_result is not None:
			print(part.code_execution_result.output)
	try:
		cand = response.candidates[0]

		if (
			cand.content
			and cand.content.parts
			and cand.content.parts[0].function_call
		):
			fc = cand.content.parts[0].function_call
			return {
				"name": fc.name,
				"arguments": fc.args,
			}

		# -------------------------------------------------------
		# ❌ NO FUNCTION CALL – USE SAFE FALLBACK
		# -------------------------------------------------------
		print("❌ No function call found.")
		print("Finish reason:", cand.finish_reason)

		# 1. Pick template if available
		if extracted["payload_templates"]:
			template = extracted["payload_templates"][0]
			email = template.get("email", app.state.user_email)
			secret = template.get("secret", app.state.user_secret)
		else:
			# 2. No template → use stored values
			email = app.state.user_email
			secret = app.state.user_secret

		fallback_payload = {
			"email": email,
			"secret": secret,
			"url": extracted["current_url"],
			"answer": "anything"
		}

		return {
			"name": "submit_answer",
			"arguments": {
				"submit_url": extracted["submit_url"],
				"payload": fallback_payload,
			}
		}

	except Exception as e:
		print("❌ Invalid LLM response:", e)
		print(response)

		# SAME FALLBACK HERE TOO
		if extracted["payload_templates"]:
			template = extracted["payload_templates"][0]
			email = template.get("email", app.state.user_email)
			secret = template.get("secret", app.state.user_secret)
		else:
			email = app.state.user_email
			secret = app.state.user_secret

		fallback_payload = {
			"email": email,
			"secret": secret,
			"url": extracted["current_url"],
			"answer": "anything"
		}

		return {
			"name": "submit_answer",
			"arguments": {
				"submit_url": extracted["submit_url"],
				"payload": fallback_payload,
			}
		}



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

	print("response by server:", result)

	# 🔥 If server sends next URL → continue solving workflow
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

	if not llm_output:
		print("❌ LLM returned nothing.")
		return

	print("LLM output received:", llm_output)

	submit_url = llm_output["arguments"]["submit_url"]
	payload = llm_output["arguments"]["payload"]
	payload["url"] = extracted['current_url']
	payload["email"] = app.state.user_email
	payload["secret"] = app.state.user_secret
	await submit_answer(app,submit_url, payload)

async def solve_quiz_chain(page: Page, start_url: str):
	print("Starting quiz solving chain")
	await solve_quiz_step(page, start_url)

@app.post("/task")
async def handle_task(data: dict, background_tasks: BackgroundTasks):
	secret = os.getenv("SECRET")
	print(data)
	if data.get("secret") == secret:
		# Run the task in background (not implemented here)
		app.state.user_email = data["email"]
		app.state.user_secret = data["secret"]
		background_tasks.add_task(solve_quiz_chain, app.state.page, data['url'])
		return {"message": "Secret Matches!", "status_code": 200}
	else:
		return {"message": "Secret does not match", "status_code": 403}


if __name__ == "__main__":
	import uvicorn
	uvicorn.run(app, port=8000)